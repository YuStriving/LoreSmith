from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from ainovel_py.domain.runtime import FlowState
from ainovel_py.host.events import Event

from ..hints import HintAction, plan_actions
from ..state import GraphState

MAX_STEPS = 12
RUN_CONTINUE_SENTINEL = "__RUN_CONTINUE__"
DEFAULT_ACTION = "checkpoint"
PAUSE_INTERVAL = 5
REASONING_TRUNCATE_LENGTH = 80

# 每批次最大章节数（防无限循环安全网）
# 长篇小说创作（用户请求"写一本 xxx 小说"）每完成 N 章后自动暂停，
# 等待用户重新确认方向与规划，避免一次性消耗大量 token。
MAX_BATCH_CHAPTERS = 5
"""每批次最大章节数。超过此值后 checkpoint 节点触发 PendingRunCheckpoint，
要求用户确认下一批章节方向。这是 LangGraph 死循环防护的第二层（业务层兜底）。"""


def _append_line(state: GraphState, line: str) -> None:
    """向 state 的 out_lines 追加一行日志文本。

    out_lines 是图执行过程中的输出行列表，最终会通过 emit_stream 发送给前端展示，
    用于实时反馈工作流进度。

    Args:
        state: 图状态字典
        line: 要追加的日志行
    """
    lines = list(state.get("out_lines") or [])
    lines.append(line)
    state["out_lines"] = lines


def _set_pending_actions(state: GraphState, actions: list[str]) -> None:
    """设置待处理的动作队列和当前动作。

    将 actions 列表写入 pending_actions，并将首个动作设为 pending_action。
    队列为空时，pending_action 回退到 DEFAULT_ACTION（"checkpoint"）。

    Args:
        state: 图状态字典
        actions: 待执行的动作名称列表（如 ["arc_summary", "volume_summary"]）
    """
    state["pending_actions"] = actions
    state["pending_action"] = actions[0] if actions else DEFAULT_ACTION


def _pop_pending_action(state: GraphState) -> None:
    """弹出并消费队列中的第一个待处理动作。

    从 pending_actions 弹出首项，将新的首项设为 pending_action。
    队列变空时，pending_action 回退到 DEFAULT_ACTION。

    Args:
        state: 图状态字典
    """
    actions = list(state.get("pending_actions") or [])
    if actions:
        actions.pop(0)
    state["pending_actions"] = actions
    state["pending_action"] = actions[0] if actions else DEFAULT_ACTION


def _enqueue_hint_actions(state: GraphState, actions: list[HintAction]) -> str:
    """将 HintAction 列表转化为 pending_actions 队队并返回下一步动作。

    调用 plan_actions 将语义化动作信号转化为 ActionPlan，
    然后将 queue 写入 pending_actions。如果队列非空，同时追加日志行。

    Args:
        state: 图状态字典
        actions: HintAction 枚举列表

    Returns:
        ActionPlan.next_action 的值，即下一步应跳转的目标节点名
    """
    plan = plan_actions(actions)
    _set_pending_actions(state, list(plan.queue))
    if plan.queue:
        _append_line(state, "[hint-actions] " + ", ".join(plan.queue))
    return plan.next_action


def _is_rewrite_mode(progress: Any) -> bool:
    """判断当前是否处于重写/打磨模式。

    检查 progress 的 flow 状态是否为 REWRITING 或 POLISHING，
    且存在待重写的章节队列。

    Args:
        progress: 进度对象（Progress），包含 flow、pending_rewrites 等字段

    Returns:
        True 表示当前处于重写或打磨模式
    """
    return bool(progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites)


def ensure_novel_context(runtime: Any, state: GraphState) -> dict[str, Any]:
    """懒加载小说上下文：有缓存直接返回，无则从 store 加载并缓存到 state["context"]。

    子图按需调用，首次加载后后续子图直接复用，避免重复读取 store。

    Args:
        runtime: LangGraphRuntime 实例
        state: 图状态字典

    Returns:
        小说上下文字典
    """
    cached = state.get("context")
    if cached:
        return cached
    chapter = int(state.get("current_chapter") or 1)
    context = runtime.runner.call_tool("novel_context", {"chapter": chapter}) or {}
    if _is_rewrite_mode(runtime.store.progress.load()):
        rewrite_agent = runtime.get_agent("rewrite")
        context = rewrite_agent.build_rewrite_context(runtime.store.progress.load(), context)
    state["context"] = context
    return context


def _resume_from_checkpoint(runtime: Any, state: GraphState, pending_checkpoint: Any, seed_text: str) -> str:
    """处理"待确认检查点"恢复场景。

    当系统因达到暂停间隔（每 PAUSE_INTERVAL 章）产生检查点时，
    需要用户确认后才能继续。此函数判断用户是否确认继续：
    - seed_text 为 RUN_CONTINUE_SENTINEL → 清除检查点，返回 "novel_context" 继续执行
    - 其他值 → 返回 "finish" 终止流程，等待用户再次启动

    Args:
        runtime: LangGraphRuntime 实例
        state: 图状态字典
        pending_checkpoint: 待确认的检查点对象（PendingRunCheckpoint）
        seed_text: 用户输入的种子文本（用于确认继续）

    Returns:
        下一步动作："novel_context"（继续）或 "finish"（终止等待）
    """
    current_chapter = pending_checkpoint.next_chapter
    if seed_text == RUN_CONTINUE_SENTINEL:
        runtime.store.signals.clear_pending_checkpoint()
        _append_line(state, f"[run] confirmation accepted -> next_chapter={pending_checkpoint.next_chapter}")
        return "novel_context"
    _append_line(state, f"[resume] awaiting_confirmation -> pause_after={pending_checkpoint.pause_after_chapter}")
    return "finish"


def _resume_from_pending_commit(state: GraphState, pending: Any) -> tuple[int, str]:
    """处理"待提交章节"恢复场景。

    当上一轮 commit 流程中断（如草稿已生成但未完成提交）时，
    从 store 中恢复未完成的提交任务，直接跳转到 commit_chapter 节点。

    Args:
        state: 图状态字典
        pending: 待提交的章节信息对象

    Returns:
        (chapter, next_action) 元组：待提交章节号和 "commit_chapter" 动作
    """
    _append_line(state, f"[resume] pending_commit -> chapter={pending.chapter} stage={pending.stage}")
    return pending.chapter, "commit_chapter"


def _resume_from_in_progress(runtime: Any, state: GraphState, progress: Any, latest: Any, current_chapter: int) -> tuple[int, str]:
    """处理"进行中章节"恢复场景。

    当某章节正在生成过程中中断时，根据最后保存的检查点步骤（step）
    决定从哪个阶段恢复：
    - consistency_check / draft 步骤 → 已有草稿，跳到 commit_chapter
    - plan 步骤 → 检查本地是否有 draft，有则 commit 否则重新 generate_draft
    - 其他 / 未知 → 重新从 novel_context 开始

    Args:
        runtime: LangGraphRuntime 实例
        state: 图状态字典
        progress: 进度对象
        latest: 最新的全局检查点
        current_chapter: 当前的默认章节号

    Returns:
        (chapter, next_action) 元组：进行中章节号和恢复后的下一步动作
    """
    chapter = progress.in_progress_chapter
    step = latest.step if latest and latest.scope.kind == "chapter" and latest.scope.chapter == chapter else ""
    if step in ("consistency_check", "draft"):
        next_action = "commit_chapter"
    elif step == "plan":
        draft_content = runtime.store.drafts.load_draft(chapter)
        if draft_content:
            next_action = "commit_chapter"
            _append_line(state, f"[resume] found_local_draft -> chapter={chapter} skip_generate")
        else:
            next_action = "generate_draft"
    else:
        next_action = "novel_context"
    _append_line(state, f"[resume] in_progress -> chapter={chapter} step={step or 'unknown'}")
    return chapter, next_action


def _resume_from_rewrite_queue(state: GraphState, progress: Any, rewrite_mode: str) -> tuple[int, str]:
    """处理"重写队列"恢复场景。

    当系统处于重写/打磨模式时，从 pending_rewrites 队列中取出
    第一个待重写的章节号，准备进入重写流程。

    Args:
        state: 图状态字典
        progress: 进度对象（需包含 pending_rewrites 列表）
        rewrite_mode: 当前重写模式（"rewrite" 或 "polish"）

    Returns:
        (chapter, mode) 元组：待重写章节号和重写模式
    """
    chapter = progress.pending_rewrites[0]
    mode = rewrite_mode or "rewrite"
    _append_line(state, f"[resume] rewrite_queue -> chapter={chapter} mode={mode}")
    return chapter, mode or "rewrite"


def route_after_load(state: GraphState) -> str:
    """load_runtime_context 节点的条件边路由函数。

    根据 load_runtime_context 设置的 pending_action 决定下一步跳转目标。
    支持的路由：generate_draft（恢复到草稿阶段）、commit_chapter（恢复到提交阶段）、
    rewrite/polish（进入重写）、finish（终止）、默认 novel_context（正常开始）。

    Args:
        state: 图状态字典

    Returns:
        目标节点名字符串
    """
    action = str(state.get("pending_action") or "novel_context")
    if action == "generate_draft":
        return "generate_draft"
    if action == "commit_chapter":
        return "commit_chapter"
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "finish":
        return "finish"
    return "novel_context"


def route_after_plan(state: GraphState) -> str:
    """plan_chapter 节点的条件边路由函数。

    规划完成后通常跳转到 generate_draft 生成草稿；
    仅在特殊情况下（如 finish 信号）直接终止。

    Args:
        state: 图状态字典

    Returns:
        目标节点名字符串（"generate_draft" 或 "finish"）
    """
    action = str(state.get("pending_action") or "generate_draft")
    if action == "finish":
        return "finish"
    return "generate_draft"


def _route_by_action(state: GraphState, default: str) -> str:
    """通用动作路由函数，根据 pending_action 匹配目标节点。

    被 route_after_commit 和 route_after_checkpoint 复用，
    消除了两个路由函数之间的重复分支逻辑。

    支持的路由映射：
    - rewrite/polish → "rewrite"
    - arc_summary → "arc_summary"
    - volume_summary → "volume_summary"
    - expand_arc → "expand_arc"
    - review → "review"
    - finish → "finish"
    - 其他 → default 参数

    Args:
        state: 图状态字典
        default: 未匹配时的默认目标节点名

    Returns:
        目标节点名字符串
    """
    action = str(state.get("pending_action") or default)
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "arc_summary":
        return "arc_summary"
    if action == "volume_summary":
        return "volume_summary"
    if action == "expand_arc":
        return "expand_arc"
    if action == "review":
        return "review"
    if action == "finish":
        return "finish"
    return default


def route_after_commit(state: GraphState) -> str:
    """commit_chapter 节点的条件边路由函数（经 supervisor 后）。

    复用 _route_by_action，默认目标为 "checkpoint"。
    覆盖 commit 后的所有可能路径：review、rewrite、polish、
    arc_summary、volume_summary、expand_arc、finish。

    Args:
        state: 图状态字典

    Returns:
        目标节点名字符串
    """
    return _route_by_action(state, "checkpoint")


def route_after_checkpoint(state: GraphState) -> str:
    """checkpoint 节点的条件边路由函数。

    特殊处理 "novel_context" 和 "continue"（两者均指向 novel_context 节点开始新章节），
    其余情况复用 _route_by_action，默认目标为 "finish"。

    Args:
        state: 图状态字典

    Returns:
        目标节点名字符串
    """
    action = str(state.get("pending_action") or "finish")
    if action in {"novel_context", "continue"}:
        return "novel_context"
    return _route_by_action(state, "finish")


SUPERVISOR_ACTION_MAP = {
    "architect": "novel_context",
    "writer": "generate_draft",
    "editor": "review",
    "rewrite": "rewrite",
    "arc_summary": "arc_summary",
    "volume_summary": "volume_summary",
    "expand_arc": "expand_arc",
    "checkpoint": "checkpoint",
    "FINISH": "finish",
}
"""Supervisor Agent 输出的 next_agent 名称到图节点名的映射表。"""

VALID_SUPERVISOR_TARGETS = frozenset(SUPERVISOR_ACTION_MAP.values())
"""合法的 Supervisor 路由目标集合，用于校验决策输出的有效性。"""


def route_from_supervisor(state: GraphState) -> str:
    """supervisor 节点的条件边路由函数。

    从 state["supervisor_decision"] 中提取 next_agent 字段，
    通过 SUPERVISOR_ACTION_MAP 映射为图节点名。
    映射失败或 decision 无效时，回退到 route_after_commit（硬编码路由安全网）。

    Args:
        state: 图状态字典，需包含 supervisor_decision 字段

    Returns:
        目标节点名字符串
    """
    decision = state.get("supervisor_decision")
    if decision and isinstance(decision, dict):
        next_agent = str(decision.get("next_agent") or "")
        target = SUPERVISOR_ACTION_MAP.get(next_agent)
        if target and target in VALID_SUPERVISOR_TARGETS:
            return target
    return route_after_commit(state)


# ============================================================
# 优化 ①-1：commit 后置任务并行执行
# ============================================================
SUMMARY_TASK_ARC = "arc_summary"
SUMMARY_TASK_VOLUME = "volume_summary"
SUMMARY_TASK_EXPAND = "expand_arc"
SUMMARY_TASKS_ALL = {SUMMARY_TASK_ARC, SUMMARY_TASK_VOLUME, SUMMARY_TASK_EXPAND}


def _run_summary_task(
    runtime: Any,
    state: GraphState,
    task: str,
    out_lines: list[str],
) -> dict[str, Any]:
    """单任务包装：执行单个 summary 任务（arc_summary / volume_summary / expand_arc）。

    Args:
        runtime: LangGraphRuntime 实例
        state: 图状态字典
        task: 任务名（arc_summary / volume_summary / expand_arc）
        out_lines: 输出日志行列表（线程安全追加）

    Returns:
        结果字典 {"task": ..., "ok": bool, "result": ..., "error": str (if failed)}
    """
    chapter = int(state.get("current_chapter") or 1)
    try:
        if task == SUMMARY_TASK_ARC:
            from ..review_flow import save_arc_summary_followup
            save_arc_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines)
            return {"task": task, "ok": True, "result": "arc_summary saved"}
        if task == SUMMARY_TASK_VOLUME:
            from ..review_flow import save_volume_summary_followup
            progress = runtime.store.progress.load()
            volume = max(1, progress.current_volume) if progress else 1
            save_volume_summary_followup(
                runtime.runner, runtime.emit_event, chapter, out_lines,
                volume=volume, always=True,
            )
            return {"task": task, "ok": True, "result": "volume_summary saved"}
        if task == SUMMARY_TASK_EXPAND:
            from .summary_nodes import _execute_expand_arc_safe
            _execute_expand_arc_safe(runtime, state, chapter, out_lines)
            return {"task": task, "ok": True, "result": "expand_arc saved"}
        return {"task": task, "ok": False, "error": f"unknown task: {task}"}
    except Exception as e:
        return {"task": task, "ok": False, "error": str(e)}


def _execute_parallel_summaries(
    runtime: Any,
    state: GraphState,
    tasks: list[str],
) -> dict[str, Any]:
    """并行执行多个 summary 任务（优化 ①-1）。

    适用于 commit 后 hint_actions 一次性产出多个 summary 任务的场景。
    相比串行执行，N 个任务节省 (N-1) * task_time 延迟。

    线程安全：
    - 每个任务调用独立的 summary 工具（save_arc_summary / save_volume_summary / save_foundation）
    - 文件 IO 通过 store.io 的 per-directory 锁（优化 ①-3）保证原子性
    - 共享的 out_lines 列表通过线程局部缓冲区追加，最后合并到 state

    Args:
        runtime: LangGraphRuntime 实例
        state: 图状态字典
        tasks: 任务名列表（元素为 SUMMARY_TASKS_ALL 子集）

    Returns:
        聚合结果字典 {"results": {task_name: result_dict}, "all_ok": bool, "duration": float}
    """
    import time

    if not tasks:
        return {"results": {}, "all_ok": True, "duration": 0.0}

    # 过滤未知任务
    valid_tasks = [t for t in tasks if t in SUMMARY_TASKS_ALL]
    if not valid_tasks:
        return {"results": {}, "all_ok": True, "duration": 0.0}

    # 线程局部缓冲区：每个任务独立写自己的日志，避免锁竞争
    thread_buffers: dict[str, list[str]] = {task: [] for task in valid_tasks}
    t_start = time.time()
    results: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=len(valid_tasks)) as pool:
        future_map = {
            pool.submit(_run_summary_task, runtime, state, task, thread_buffers[task]): task
            for task in valid_tasks
        }
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                results[task] = future.result()
            except Exception as e:
                results[task] = {"task": task, "ok": False, "error": str(e)}

    # 合并所有线程的输出日志到 state
    main_out_lines = list(state.get("out_lines") or [])
    for task in valid_tasks:
        buf = thread_buffers.get(task, [])
        if buf:
            main_out_lines.extend(buf)
    state["out_lines"] = main_out_lines

    all_ok = all(r.get("ok") for r in results.values())
    duration = time.time() - t_start

    # 追加汇总日志
    _append_line(state, f"[parallel_summaries] tasks={valid_tasks} all_ok={all_ok} duration={duration:.2f}s")

    return {"results": results, "all_ok": all_ok, "duration": duration}


def is_parallel_summary_set(tasks: list[str]) -> bool:
    """判断任务列表是否适合并行执行。

    条件：
    - 长度 > 1
    - 全部任务都在 SUMMARY_TASKS_ALL 集合中
    - 不包含 expand_arc 时的额外条件：expand_arc 不能与 arc_summary 并行（共享进度状态）
    """
    if not tasks or len(tasks) <= 1:
        return False
    summary_set = {SUMMARY_TASK_ARC, SUMMARY_TASK_VOLUME}
    # 简单情况：仅 arc_summary / volume_summary 组合
    if all(t in summary_set for t in tasks):
        return True
    # expand_arc 也可加入（调用 save_foundation，与 summaries 不同目录）
    if all(t in SUMMARY_TASKS_ALL for t in tasks):
        return True
    return False

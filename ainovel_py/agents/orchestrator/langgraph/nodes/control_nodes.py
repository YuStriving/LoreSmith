from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.domain.writing import PendingRunCheckpoint

from .helpers import (
    MAX_BATCH_CHAPTERS,
    MAX_STEPS,
    PAUSE_INTERVAL,
    REASONING_TRUNCATE_LENGTH,
    SUPERVISOR_ACTION_MAP,
    _append_line,
)

# supervisor 连续 LLM 失败上限（超过则强制 finish）
SUPERVISOR_MAX_CONSECUTIVE_FAILURES = 3
# P1-001 修复：supervisor 连续路由到 checkpoint 的弹跳上限
MAX_CHECKPOINT_SUPERVISOR_BOUNCES = 2
# P1-001 修复：checkpoint 连续访问次数上限（兜底层）
MAX_CHECKPOINT_VISITS = 4
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def checkpoint_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建检查点/流程控制节点工厂函数。

    这是工作流的**控制中枢**，负责：
    1. 消费 pending_actions 队列（有排队动作时优先执行）
    2. 判断是否全部完成（章节总数已达且最后一章已完成）
    3. 判断是否超步数上限或被中止
    4. 每 PAUSE_INTERVAL 章生成一个暂停检查点（需用户确认后继续）
    5. 正常情况下推进到下一章

    暂停机制：每完成 PAUSE_INTERVAL（默认 5）章后生成 PendingRunCheckpoint，
    通过 emit_checkpoint_pending 通知前端，等待用户确认后才能继续。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，设置 state["current_chapter"] 和 state["pending_action"]
    """
    def _node(state: GraphState) -> GraphState:
        # P1-001 修复 L2：checkpoint 访问计数器（兜底层）
        checkpoint_visits = int(state.get("_checkpoint_visits") or 0) + 1
        state["_checkpoint_visits"] = checkpoint_visits

        if checkpoint_visits > MAX_CHECKPOINT_VISITS:
            state["pending_action"] = "finish"
            _append_line(state, f"[checkpoint] {checkpoint_visits} visits without progress -> force finish")
            return state

        progress = runtime.store.progress.load()
        chapter = int(state.get("current_chapter") or 1)
        completed = list(progress.completed_chapters) if progress else []
        total = progress.total_chapters if progress else 0
        steps = len(completed)
        pending_actions = list(state.get("pending_actions") or [])

        if pending_actions:
            state["pending_action"] = pending_actions[0]
            return state

        if progress and total > 0 and chapter >= total and chapter in completed:
            state["pending_action"] = "finish"
            return state

        if steps >= MAX_STEPS or runtime.is_aborted:
            state["pending_action"] = "finish"
            return state

        next_chapter = progress.next_chapter() if progress else chapter + 1

        # 分段退出（spec: langgraph-no-infinite-loop）
        # 1) 有 total_chapters：维持原有行为，每 PAUSE_INTERVAL 章触发暂停
        # 2) freeform 模式（total_chapters=0）：每完成 MAX_BATCH_CHAPTERS 章也触发暂停
        # 这样长篇小说任务（如"写 100 章"）不会一口气写到底，每 5 章就寻求用户接管
        should_pause = False
        if steps > 0 and steps % PAUSE_INTERVAL == 0:
            should_pause = True
        elif total <= 0 and steps > 0 and steps % MAX_BATCH_CHAPTERS == 0:
            should_pause = True

        if should_pause:
            pending = PendingRunCheckpoint(
                pause_after_chapter=max(completed) if completed else chapter,
                next_chapter=next_chapter,
                completed_count=steps,
                reason="batch_complete",   # spec: 默认 batch_complete
            )
            runtime.store.signals.save_pending_checkpoint(pending)
            runtime.emit_checkpoint_pending(pending)
            state["current_chapter"] = next_chapter
            state["pending_action"] = "finish"
            _append_line(state, f"[checkpoint] batch_complete -> pause ch{max(completed) if completed else chapter} (steps={steps})")
            return state

        state["current_chapter"] = next_chapter
        state["pending_action"] = "continue"
        return state

    return _node


def finish_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建终止节点工厂函数。

    工作流终点节点，仅将 pending_action 设为 "finish"，
    触发图的 END 边结束执行。

    注意：当前实现较简单，未来可在此处添加终止前清理逻辑
    （如保存最终状态、发射完成事件等）。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，设置 state["pending_action"] = "finish"
    """
    def _node(state: GraphState) -> GraphState:
        state["pending_action"] = "finish"
        return state

    return _node


def supervisor_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建 Supervisor 动态路由节点工厂函数。

    多 Agent 架构的**调度核心**，调用 SupervisorAgent 通过 LLM 结构化输出生成决策：
    - next_agent: 下一步应调度的目标 Agent 名称
    - reasoning: 决策理由
    - task_instruction: 给目标 Agent 的具体指令

    决策成功时通过 SUPERVISOR_ACTION_MAP 映射为图节点名；
    失败时回退到 route_after_commit（硬编码路由安全网）。

    死循环防护（P0-2 + P0-3 修复）：
    - 决策成功时更新 current_tag（修复 supervisor 直接路由子图时 current_tag 不更新的 bug）
    - 连续 LLM 失败超过 SUPERVISOR_MAX_CONSECUTIVE_FAILURES 时强制 finish（防止 supervisor↔checkpoint 来回跳）

    此节点是 commit_chapter、review、arc_summary、volume_summary 四个节点的统一汇聚点，
    所有这些节点执行完毕后都会先经过 supervisor 再分发到下一个目标。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["supervisor_decision"] 和 state["pending_action"]
    """
    def _node(state: GraphState) -> GraphState:
        from ainovel_py.agents.roles.supervisor import SupervisorAgent

        supervisor = runtime.get_agent("supervisor")
        if not isinstance(supervisor, SupervisorAgent):
            state["supervisor_decision"] = None
            return state

        # P0-3：连续失败退避
        consecutive_failures = int(state.get("_supervisor_consecutive_failures") or 0)
        if consecutive_failures >= SUPERVISOR_MAX_CONSECUTIVE_FAILURES:
            state["supervisor_decision"] = None
            state["pending_action"] = "finish"
            _append_line(state, f"[supervisor] {consecutive_failures} consecutive failures -> force finish")
            return state

        # 规则优先：review 判 rewrite/polish 时直接路由，不问 LLM
        # 遵循项目 "rule-first, LLM-fallback" 理念，尊重 review 的专业判断
        if state.get("last_completed_tag") == "editor_review":
            review_result = state.get("latest_review_result") or {}
            verdict = str(review_result.get("final_verdict") or "")
            if verdict in ("rewrite", "polish"):
                state["supervisor_decision"] = {
                    "next_agent": "rewrite",
                    "reasoning": f"review_verdict={verdict}, rule-first skip LLM",
                    "task_instruction": "",
                }
                state["pending_action"] = "rewrite"
                state["current_tag"] = "writer"
                state["_supervisor_consecutive_failures"] = 0
                _append_line(state, f"[supervisor] rule-first: review={verdict} -> rewrite (skip LLM)")
                return state

        result = supervisor.execute(state=state)
        decision = result.get("supervisor_decision")
        pending_action = result.get("pending_action", "checkpoint")

        state["supervisor_decision"] = decision
        state["pending_action"] = pending_action

        if decision:
            # P0-2：决策成功时，根据 SUPERVISOR_ACTION_MAP 更新 current_tag
            # 这样当 supervisor 直接路由到子图时，collect 能拿到正确的 last_completed_tag
            next_agent = str(decision.get("next_agent") or "")
            mapped_tag = SUPERVISOR_ACTION_MAP.get(next_agent, "")
            if mapped_tag:
                state["current_tag"] = mapped_tag
            # 重置连续失败计数
            state["_supervisor_consecutive_failures"] = 0

            # P1-001 修复 L1：supervisor→checkpoint 弹跳检测
            if mapped_tag == "checkpoint":
                last_tag = str(state.get("last_completed_tag") or "")
                if last_tag in {"checkpoint", "parallel_summaries"}:
                    # 刚从 checkpoint 来又要回 checkpoint → 弹跳
                    bounces = int(state.get("_checkpoint_supervisor_bounces") or 0) + 1
                    state["_checkpoint_supervisor_bounces"] = bounces
                    if bounces >= MAX_CHECKPOINT_SUPERVISOR_BOUNCES:
                        # 超过阈值 → 强制走 dispatch 正常流程
                        state["current_tag"] = "architect"
                        state["pending_action"] = "novel_context"
                        _append_line(state, f"[supervisor] bounce limit {bounces} -> override to dispatch")
                    else:
                        _append_line(state, f"[supervisor] checkpoint bounce {bounces}/{MAX_CHECKPOINT_SUPERVISOR_BOUNCES}")
                else:
                    # 首次从非 checkpoint 节点路由到 checkpoint → 正常
                    state["_checkpoint_supervisor_bounces"] = 0
            else:
                state["_checkpoint_supervisor_bounces"] = 0

            _append_line(state, f"[supervisor] next={next_agent} reason={decision.get('reasoning', '')[:REASONING_TRUNCATE_LENGTH]}")
        else:
            # 递增连续失败计数
            state["_supervisor_consecutive_failures"] = consecutive_failures + 1
            _append_line(state, f"[supervisor] fallback to hardcoded routing (failures={consecutive_failures + 1})")

            # 失败兜底也要尊重 review 的路由决策
            # 当 review 判 rewrite/polish 但 supervisor LLM 失败时，
            # 不应走默认 checkpoint 路由，而应尊重 review 的判断
            if state.get("last_completed_tag") == "editor_review":
                review_result = state.get("latest_review_result") or {}
                verdict = str(review_result.get("final_verdict") or "")
                if verdict in ("rewrite", "polish"):
                    state["pending_action"] = "rewrite"
                    state["current_tag"] = "writer"
                    _append_line(state, f"[supervisor] fallback: review={verdict} -> rewrite (respect review)")

        return state

    return _node

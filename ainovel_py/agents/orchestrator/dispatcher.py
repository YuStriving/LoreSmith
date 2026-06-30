from __future__ import annotations

import json
from typing import Any

from .tags import TaskTag


# ============================================================
# 阶段 B：高频确定性路径 → 规则直接命中（零 LLM 延迟）
# 覆盖 80% 的真实工作流路径，未命中才走 LLM 兜底
# ============================================================
# key = (last_completed_agent, current_step)
# value = next_agent_name（与 AgentSpec.name 对齐）
FAST_RULES: dict[tuple[str, str], str] = {
    ("",                  "load_context"):   "architect",
    ("architect",         "write_chapter"):  "writer",
    ("writer",            "commit_chapter"): "editor_commit",
    ("editor_commit",     "review_chapter"): "editor_review",
    ("editor_review",     "rewrite_chapter"): "writer",
    ("writer",            "rewrite_chapter"): "editor_commit",
    ("arc_summary",       "checkpoint"):     "checkpoint",
    ("volume_summary",    "checkpoint"):     "checkpoint",
    ("expand_arc",        "checkpoint"):     "checkpoint",
}


def dispatch_next(state: dict[str, Any]) -> TaskTag:
    """主 Agent 的核心调度函数（v1 纯规则链，保留向后兼容）。

    阶段 B 之前的旧接口。语义未变：last_completed_tag 决定下一步，返回 TaskTag。
    阶段 B 之后推荐使用 dispatch_next_v2()，它会经过 AgentRegistry + LLM 决策。
    """
    last_tag = str(state.get("last_completed_tag") or "")
    current_tag = str(state.get("current_tag") or "")
    pending_action = str(state.get("pending_action") or "")

    # 规则 1：pending_action 中有直接指令
    if pending_action:
        tag = _map_pending_action_to_tag(pending_action)
        if tag:
            return tag

    # 规则 2：根据上一个完成的任务决定
    if last_tag:
        return _decide_after_completion(state, last_tag)

    # 规则 3：首次启动（无 last_completed_tag），从 load_context 后的状态推断
    return _decide_initial(state)


def dispatch_next_v2(
    state: dict[str, Any],
    registry: Any,                            # AgentRegistry
    llm_client: Any | None = None,            # OpenAICompatClient, None 表示纯规则
    *,
    log_path: str | None = None,
) -> str:
    """主 Agent 的调度函数 v2：规则优先 + LLM 兜底（阶段 B 新增）。

    设计目标：
    - 80% 高频路径走 FAST_RULES，零 LLM 延迟
    - 未命中规则时调用 LLM 决策，但只能在 registry 候选 agent 中选择（白名单防御）
    - LLM 决策结果落 dispatch_log.jsonl（可选），便于回放
    - LLM 故障时安全兜底到 supervisor

    Args:
        state: 当前图状态字典
        registry: AgentRegistry 实例，提供 spec 元数据
        llm_client: LLM 客户端；为 None 时强制走纯规则模式（用于回归测试）
        log_path: LLM 决策日志路径；为 None 时不写日志

    Returns:
        next_agent_name（与 AgentSpec.name 对齐），如 "writer" / "editor_commit" / "supervisor"

    Raises:
        RuntimeError: LLM 返回未在候选中的 agent 名
    """
    last_completed = str(state.get("last_completed_tag") or "")
    current_step = str(state.get("current_step") or _infer_current_step(state))

    # 1) 规则层（命中即返回，不调 LLM）
    if (last_completed, current_step) in FAST_RULES:
        return FAST_RULES[(last_completed, current_step)]

    # 2) 未提供 LLM 客户端 → 退回纯规则（通过 v1 dispatcher）
    if llm_client is None:
        return dispatch_next(state).value

    # 3) 候选白名单：当前 agent 的 allowed_next ∩ registry 全部
    candidates = registry.filter_candidates(last_completed, exclude={"supervisor"})
    # supervisor 永远作为兜底候选
    if registry.has("supervisor") and "supervisor" not in candidates:
        candidates = list(candidates) + ["supervisor"]

    # 4) LLM 决策
    decision = _llm_decide_next(state, candidates, registry, llm_client, log_path)

    # 5) 白名单校验
    if decision not in candidates:
        raise RuntimeError(
            f"LLM returned out-of-scope agent: {decision!r} "
            f"(candidates={candidates!r})"
        )
    return decision


def _infer_current_step(state: dict[str, Any]) -> str:
    """根据 state 推断 current_step（用于 v2 的 FAST_RULES 命中）。"""
    # 流程入口
    if not state.get("last_completed_tag"):
        return "load_context"
    # pending_action 映射
    pa = str(state.get("pending_action") or "")
    mapping = {
        "generate_draft": "write_chapter",
        "commit_chapter": "commit_chapter",
        "review": "review_chapter",
        "rewrite": "rewrite_chapter",
        "polish": "rewrite_chapter",
        "arc_summary": "checkpoint",
        "volume_summary": "checkpoint",
        "expand_arc": "checkpoint",
        "finish": "checkpoint",
        "checkpoint": "checkpoint",
        "novel_context": "write_chapter",
        "continue": "write_chapter",
    }
    return mapping.get(pa, "load_context")


def _llm_decide_next(
    state: dict[str, Any],
    candidates: list[str],
    registry: Any,
    llm_client: Any,
    log_path: str | None,
) -> str:
    """调用 LLM 决定下一个 agent。失败时安全兜底到 supervisor。"""
    spec_lines = "\n".join(
        f"- {s.name}: {s.description} (工具: {','.join(s.tools) or '无'})"
        for s in registry.all_specs() if s.name in candidates
    )
    commit_hints = (state.get("latest_commit_result") or {}).get("system_hints", [])
    review_verdict = (state.get("latest_review_result") or {}).get("final_verdict", "")
    prompt = (
        "你是小说创作主编调度器，根据当前工作流状态从候选 Agent 中选择下一步。\n\n"
        f"当前章节: {state.get('current_chapter')}\n"
        f"上一完成节点: {state.get('last_completed_tag') or '无'}\n"
        f"提交结果 hints: {commit_hints}\n"
        f"评审结论: {review_verdict}\n"
        f"待处理队列: {state.get('pending_actions', [])}\n\n"
        f"可选 Agent（必须从下列名称中选择一个）：\n{spec_lines}\n\n"
        '请输出严格 JSON：{"next_agent": "<name>", "reasoning": "<简述>"}'
    )

    raw: str = ""
    decision = "supervisor"  # 安全兜底
    try:
        raw = llm_client.complete(
            system_prompt="你是主编调度器，只返回 JSON。",
            user_prompt=prompt,
            temperature=0.1,
        )
        data = json.loads(raw)
        decision = str(data.get("next_agent") or "supervisor")
    except Exception:
        # 解析失败 → 兜底到 supervisor
        decision = "supervisor"

    # 写日志（可选）
    if log_path:
        try:
            import os
            import time
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.time(),
                    "state": {k: state.get(k) for k in
                              ("current_chapter", "last_completed_tag",
                               "pending_actions", "pending_action")},
                    "candidates": candidates,
                    "prompt": prompt,
                    "raw": raw,
                    "decision": decision,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志失败不影响主流程

    return decision


# ============================================================
# v1 旧版辅助函数（保留向后兼容）
# ============================================================


def _map_pending_action_to_tag(action: str) -> TaskTag | None:
    """将旧的 pending_action 值映射为 TaskTag。"""
    mapping = {
        "generate_draft": TaskTag.WRITE_CHAPTER,
        "commit_chapter": TaskTag.COMMIT_CHAPTER,
        "review": TaskTag.REVIEW_CHAPTER,
        "rewrite": TaskTag.REWRITE_CHAPTER,
        "polish": TaskTag.REWRITE_CHAPTER,
        "arc_summary": TaskTag.ARC_SUMMARY,
        "volume_summary": TaskTag.VOLUME_SUMMARY,
        "expand_arc": TaskTag.EXPAND_ARC,
        "finish": TaskTag.FINISH,
        "novel_context": TaskTag.PLAN_CHAPTER,
        "continue": TaskTag.PLAN_CHAPTER,
    }
    return mapping.get(action)


def _decide_after_completion(state: dict[str, Any], last_tag: str) -> TaskTag:
    """根据上一个完成的任务，用规则决定下一个任务。"""

    # 规划完成 → 写作
    if last_tag == TaskTag.PLAN_CHAPTER.value:
        return TaskTag.WRITE_CHAPTER

    # 写作完成 → 提交
    if last_tag == TaskTag.WRITE_CHAPTER.value:
        return TaskTag.COMMIT_CHAPTER

    # 提交完成 → 根据 hints 决定
    if last_tag == TaskTag.COMMIT_CHAPTER.value:
        return _decide_after_commit(state)

    # 评审完成 → 根据 verdict 决定
    if last_tag == TaskTag.REVIEW_CHAPTER.value:
        return _decide_after_review(state)

    # 重写完成 → 提交
    if last_tag == TaskTag.REWRITE_CHAPTER.value:
        return TaskTag.COMMIT_CHAPTER

    # 摘要完成 → checkpoint（由 checkpoint_node 决定下一章或结束）
    if last_tag in (TaskTag.ARC_SUMMARY.value, TaskTag.VOLUME_SUMMARY.value, TaskTag.EXPAND_ARC.value):
        return _decide_after_summary(state)

    # 默认：回到规划
    return TaskTag.PLAN_CHAPTER


def _decide_after_commit(state: dict[str, Any]) -> TaskTag:
    """提交完成后的规则调度。"""
    commit_result = state.get("latest_commit_result") or {}
    hints = commit_result.get("system_hints") or []

    from .langgraph.hints import parse_hint_actions, plan_actions
    actions = parse_hint_actions(hints)
    action_plan = plan_actions(actions)

    # 需要评审 → Editor 评审技能
    if action_plan.requires_review:
        return TaskTag.REVIEW_CHAPTER

    # 需要重写/打磨 → Writer 重写技能
    if action_plan.rewrite_mode:
        return TaskTag.REWRITE_CHAPTER

    # 有排队的摘要/扩展任务
    if action_plan.queue:
        return _map_pending_action_to_tag(action_plan.queue[0]) or TaskTag.PLAN_CHAPTER

    # 无特殊 hints → 下一章
    return TaskTag.PLAN_CHAPTER


def _decide_after_review(state: dict[str, Any]) -> TaskTag:
    """评审完成后的规则调度。"""
    review_result = state.get("latest_review_result") or {}
    verdict = str(review_result.get("final_verdict") or review_result.get("verdict") or "")

    # 评审通过 → 下一章
    if verdict == "accept":
        return TaskTag.PLAN_CHAPTER

    # 评审需要打磨/重写 → Writer 重写技能
    if verdict in ("polish", "rewrite"):
        return TaskTag.REWRITE_CHAPTER

    # 评审结果模糊（如 LLM 输出非标准 verdict）→ LLM 兜底
    # 也检查 hints
    hints = review_result.get("system_hints") or []
    if hints:
        from .langgraph.hints import parse_hint_actions, plan_actions
        actions = parse_hint_actions(hints)
        action_plan = plan_actions(actions)
        if action_plan.rewrite_mode:
            return TaskTag.REWRITE_CHAPTER
        if action_plan.queue:
            tag = _map_pending_action_to_tag(action_plan.queue[0])
            if tag:
                return tag

    # 默认：下一章
    return TaskTag.PLAN_CHAPTER


def _decide_after_summary(state: dict[str, Any]) -> TaskTag:
    """摘要完成后的规则调度。"""
    # 摘要完成后回到规划（下一章）
    return TaskTag.PLAN_CHAPTER


def _decide_initial(state: dict[str, Any]) -> TaskTag:
    """首次启动时的规则调度。"""
    pending_action = str(state.get("pending_action") or "")

    # load_context 已设置 pending_action
    if pending_action:
        tag = _map_pending_action_to_tag(pending_action)
        if tag:
            return tag

    # 默认：从规划开始
    return TaskTag.PLAN_CHAPTER

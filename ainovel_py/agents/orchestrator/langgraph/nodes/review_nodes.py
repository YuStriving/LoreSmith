from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.agents.roles.editor import (
    MAX_REWRITE_ATTEMPTS,
    MAX_STAGNANT_REWRITES,
    REVIEW_PASS_THRESHOLD,
    compute_weighted_score,
)
from ainovel_py.host.events import Event

from .helpers import _append_line, _enqueue_hint_actions, _is_rewrite_mode
from ..post_commit import plan_review_followup
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建评审节点工厂函数。

    对指定章节进行多维度评审（一致性、角色、节奏、连续性、伏笔、钩子、美学），
    生成结构化的评审报告并通过 save_review 工具持久化。

    评审结果是触发重写流程的唯一来源——final_verdict 为 "rewrite" 或 "polish"
    时会在后续规划中生成对应动作。

    三层退出机制（防 review↔rewrite 死循环）：
    Layer 1: 加权总分 >= REVIEW_PASS_THRESHOLD(75) → 强制 accept
    Layer 2: 连续 MAX_STAGNANT_REWRITES(2) 次分数未改善 → 强制 accept
    Layer 3: rewrite 次数 >= MAX_REWRITE_ATTEMPTS(5) → 强制 accept（兜底）

    无待评审章节（chapter <= 0）时跳过并记录日志。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["latest_review_result"] 和 state["latest_final_verdict"]
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("pending_review_for") or 0)
        if chapter <= 0:
            _append_line(state, f"[review] skipped -> chapter={chapter} not pending")
            state["pending_action"] = "checkpoint"
            return state
        editor = runtime.get_agent("editor")
        client = editor.build_client()
        review_payload = editor.generate_review_payload(client, chapter)
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = runtime.runner.call_tool("save_review", review_payload)

        # ── 加权评分 + 三层退出 ──────────────────────────────
        dimensions = review_payload.get("dimensions", [])
        weighted_score = float(review_payload.get("_weighted_score") or compute_weighted_score(dimensions))
        rewrite_attempts = int(state.get("_rewrite_attempts") or 0)
        last_score = float(state.get("_last_weighted_score") or 0)
        stagnant_count = int(state.get("_stagnant_rewrite_count") or 0)

        final_verdict = str(review_res.get("final_verdict", ""))

        if final_verdict in ("rewrite", "polish"):
            # Layer 1
            if weighted_score >= REVIEW_PASS_THRESHOLD:
                final_verdict = "accept"
                _append_line(state, f"[review] L1: weighted_score={weighted_score} >= {REVIEW_PASS_THRESHOLD} -> force accept")
            # Layer 2
            if final_verdict in ("rewrite", "polish"):
                if abs(weighted_score - last_score) < 1.0:
                    stagnant_count += 1
                else:
                    stagnant_count = 0
                if stagnant_count >= MAX_STAGNANT_REWRITES:
                    final_verdict = "accept"
                    _append_line(state, f"[review] L2: stagnant={stagnant_count} -> force accept")
            # Layer 3
            if final_verdict in ("rewrite", "polish"):
                rewrite_attempts += 1
                if rewrite_attempts >= MAX_REWRITE_ATTEMPTS:
                    final_verdict = "accept"
                    _append_line(state, f"[review] L3: rewrite_attempts={rewrite_attempts} >= {MAX_REWRITE_ATTEMPTS} -> force accept")

        state["_last_weighted_score"] = weighted_score
        state["latest_final_verdict"] = final_verdict

        if final_verdict == "accept":
            state["_rewrite_attempts"] = 0
            state["_stagnant_rewrite_count"] = 0
            state["pending_action"] = "checkpoint"
            _append_line(state, f"[tool] save_review -> accept (weighted_score={weighted_score})")
        else:
            state["_rewrite_attempts"] = rewrite_attempts
            state["_stagnant_rewrite_count"] = stagnant_count
            plan = plan_review_followup(review_res)
            next_action = _enqueue_hint_actions(state, plan.actions) if plan.actions else plan.next_action
            state["pending_action"] = next_action
            _append_line(state, f"[tool] save_review -> {final_verdict} (weighted_score={weighted_score}, attempts={rewrite_attempts})")

        state["pending_review_for"] = None
        return state

    return _node


def rewrite_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建重写入口节点工厂函数。

    此节点仅负责设置重写状态（章节号、重写模式），不调用任何 Agent 或工具。
    实际的重写工作由后续的 novel_context → plan_chapter → generate_draft 完成。

    重写模式优先级：pending_action > state 中已有的 rewrite_mode > 默认 "rewrite"。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，设置 state["current_chapter"]、state["rewrite_mode"]，
        并将 pending_action 指向 "novel_context" 以重新开始该章的生成流程
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        chapter = int(state.get("current_chapter") or 1)
        rewrite_mode = str(state.get("pending_action") or state.get("rewrite_mode") or "rewrite")
        if progress and progress.pending_rewrites:
            chapter = progress.pending_rewrites[0]
        state["current_chapter"] = chapter
        state["rewrite_mode"] = rewrite_mode
        _append_line(state, f"[rewrite] mode={rewrite_mode} chapter={chapter}")
        state["pending_action"] = "novel_context"
        return state

    return _node

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.agents.roles.editor import (
    MAX_REWRITE_ATTEMPTS,
    MAX_STAGNANT_REWRITES,
    REVIEW_PASS_THRESHOLD,
    compute_weighted_score,
)
from ainovel_py.host.events import Event

from ..nodes.helpers import _append_line, _enqueue_hint_actions, ensure_novel_context
from ..post_commit import plan_review_followup
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def build_editor_review_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Editor 的"评审章节"技能子图。

    子图流程：
    START → generate_review → save_review → END

    generate_review 节点：
    - 调用 EditorAgent.generate_review_payload() 生成评审报告

    save_review 节点：
    - 调用 save_review 工具持久化评审结果
    - 解析后续动作

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图
    """
    graph = StateGraph(GraphState)
    graph.add_node("generate_review", _generate_review_node(runtime))
    graph.add_node("save_review", _save_review_node(runtime))
    graph.add_edge(START, "generate_review")
    graph.add_edge("generate_review", "save_review")
    graph.add_edge("save_review", END)
    return graph.compile()


def _generate_review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Editor 评审技能的生成评审节点。

    通过 ensure_novel_context() 懒加载上下文，首次加载后缓存到 state["context"]。
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("pending_review_for") or state.get("current_chapter") or 0)
        if chapter <= 0:
            _append_line(state, f"[review] skipped -> chapter={chapter} not pending")
            state["latest_review_payload"] = None
            return state

        context = ensure_novel_context(runtime, state)
        editor = runtime.get_agent("editor")
        client = editor.build_client()
        review_payload = editor.generate_review_payload(client, chapter, context)
        state["latest_review_payload"] = review_payload
        _append_line(state, f"[editor] generate_review -> ch{chapter}")
        return state

    return _node


def _save_review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Editor 评审技能的保存评审节点。

    包含三层退出机制（防 review↔rewrite 死循环）：
    Layer 1: 加权总分 >= REVIEW_PASS_THRESHOLD(75) → 强制 accept
    Layer 2: 连续 MAX_STAGNANT_REWRITES(2) 次分数未改善 → 强制 accept
    Layer 3: rewrite 次数 >= MAX_REWRITE_ATTEMPTS(5) → 强制 accept（兜底）
    """
    def _node(state: GraphState) -> GraphState:
        review_payload = state.get("latest_review_payload")
        if not review_payload:
            state["pending_action"] = "checkpoint"
            return state

        chapter = int(review_payload.get("chapter") or state.get("current_chapter") or 0)
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = runtime.runner.call_tool("save_review", review_payload)
        state["latest_review_result"] = review_res

        # ── 加权评分 + 三层退出 ──────────────────────────────
        dimensions = review_payload.get("dimensions", [])
        weighted_score = float(review_payload.get("_weighted_score") or compute_weighted_score(dimensions))
        rewrite_attempts = int(state.get("_rewrite_attempts") or 0)
        last_score = float(state.get("_last_weighted_score") or 0)
        stagnant_count = int(state.get("_stagnant_rewrite_count") or 0)

        final_verdict = str(review_res.get("final_verdict", ""))

        if final_verdict in ("rewrite", "polish"):
            # Layer 1: 加权总分达标 → 强制 accept
            if weighted_score >= REVIEW_PASS_THRESHOLD:
                final_verdict = "accept"
                _append_line(state, f"[review] L1: weighted_score={weighted_score} >= {REVIEW_PASS_THRESHOLD} -> force accept")

            # Layer 2: 连续重写分数未改善 → 强制 accept
            if final_verdict in ("rewrite", "polish"):
                if abs(weighted_score - last_score) < 1.0:
                    stagnant_count += 1
                else:
                    stagnant_count = 0
                if stagnant_count >= MAX_STAGNANT_REWRITES:
                    final_verdict = "accept"
                    _append_line(state, f"[review] L2: stagnant={stagnant_count} -> force accept (score {last_score}->{weighted_score})")

            # Layer 3: 重写次数达上限 → 强制 accept
            if final_verdict in ("rewrite", "polish"):
                rewrite_attempts += 1
                if rewrite_attempts >= MAX_REWRITE_ATTEMPTS:
                    final_verdict = "accept"
                    _append_line(state, f"[review] L3: rewrite_attempts={rewrite_attempts} >= {MAX_REWRITE_ATTEMPTS} -> force accept")

        # 更新状态
        state["_last_weighted_score"] = weighted_score
        if final_verdict == "accept":
            state["_rewrite_attempts"] = 0
            state["_stagnant_rewrite_count"] = 0
            state["pending_action"] = "checkpoint"
            _append_line(state, f"[tool] save_review -> accept (weighted_score={weighted_score})")
        else:
            state["_rewrite_attempts"] = rewrite_attempts
            state["_stagnant_rewrite_count"] = stagnant_count
            plan = plan_review_followup(review_res)
            if plan.actions:
                next_action = _enqueue_hint_actions(state, plan.actions)
                state["pending_action"] = next_action
            else:
                state["pending_action"] = plan.next_action
            _append_line(state, f"[tool] save_review -> {final_verdict} (weighted_score={weighted_score}, attempts={rewrite_attempts})")

        state["pending_review_for"] = None
        return state

    return _node

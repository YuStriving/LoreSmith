from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ..nodes.helpers import _append_line, ensure_novel_context
from ..prefetch import trigger_prefetch_plan
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def build_writer_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Writer 的"写章节"技能子图。

    子图流程：
    START → generate_draft → summarize → trigger_prefetch → END

    generate_draft 节点：
    - 调用 WriterAgent.generate_chapter_with_context() 生成正文
    - 内含字数自动调整（扩写/压缩）

    summarize 节点：
    - 调用 WriterAgent.summarize_chapter() 生成章节摘要

    trigger_prefetch 节点（优化 ③）：
    - 在后台线程触发下一章（N+1）的预规划
    - 预规划与下游流程并行，architect 节点被调起时直接读缓存

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图
    """
    graph = StateGraph(GraphState)
    graph.add_node("generate_draft", _generate_draft_node(runtime))
    graph.add_node("summarize", _summarize_node(runtime))
    graph.add_node("trigger_prefetch", _trigger_prefetch_node(runtime))
    graph.add_edge(START, "generate_draft")
    graph.add_edge("generate_draft", "summarize")
    graph.add_edge("summarize", "trigger_prefetch")
    graph.add_edge("trigger_prefetch", END)
    return graph.compile()


def _generate_draft_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Writer 写作技能的核心节点：生成章节正文。"""
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = ensure_novel_context(runtime, state)
        plan = state.get("latest_plan") or {}
        contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}

        writer = runtime.get_agent("writer")
        client = writer.build_client()
        draft, word_count = writer.generate_chapter_with_context(
            client=client,
            seed_text=str(state.get("seed_text") or ""),
            chapter=chapter,
            context=context,
            plan=plan,
            contract=contract,
        )
        state["latest_draft"] = draft
        state["latest_word_count"] = word_count
        _append_line(state, f"[writer] draft_generation -> word_count={word_count}")
        return state

    return _node


def _summarize_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Writer 写作技能的摘要节点：生成章节摘要。"""
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        draft = str(state.get("latest_draft") or "")
        if not draft:
            return state

        writer = runtime.get_agent("writer")
        client = writer.build_client()
        summary = writer.summarize_chapter(client, chapter, draft)
        state["latest_summary"] = summary
        _append_line(state, f"[writer] summarize -> {summary[:60]}...")
        return state

    return _node


def _trigger_prefetch_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """优化 ③：触发下一章预规划的节点。

    在主流程里调用 trigger_prefetch_plan()，该函数会：
    1. 检查 next_chapter 是否已在缓存 / 正在预规划
    2. 若没有，启动后台线程调用 architect.build_dynamic_plan()
    3. 主流程继续走 commit / supervisor，不被预规划阻塞
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        seed_text = str(state.get("seed_text") or "")
        # 跳过错误 / 重写 / 已完成等场景
        progress = runtime.store.progress.load() if runtime and getattr(runtime, "store", None) else None
        from ainovel_py.domain.runtime import FlowState
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and (progress.pending_rewrites or []):
            _append_line(state, "[writer] trigger_prefetch skipped (rewrite mode)")
            return state
        # 已超过总章节数则不预规划
        if progress and progress.total_chapters and chapter >= progress.total_chapters:
            _append_line(state, f"[writer] trigger_prefetch skipped (chapter {chapter} >= total {progress.total_chapters})")
            return state

        next_chapter = chapter + 1
        submitted = trigger_prefetch_plan(runtime, next_chapter, seed_text)
        if submitted:
            _append_line(state, f"[writer] trigger_prefetch ch{next_chapter} submitted (background)")
        else:
            _append_line(state, f"[writer] trigger_prefetch ch{next_chapter} skipped (cached or pending)")
        return state

    return _node

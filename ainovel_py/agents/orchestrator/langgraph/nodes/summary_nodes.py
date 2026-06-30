from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.host.events import Event

from .helpers import _append_line, _pop_pending_action
from ..review_flow import save_arc_summary_followup, save_volume_summary_followup
from ..longform import generate_longform_outline_payload
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def arc_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建弧摘要保存节点工厂函数。

    调用 review_flow.save_arc_summary_followup 保存当前弧的摘要信息
    （关键事件、角色快照、风格规则等），然后消费 pending_actions 队列的首项。

    这是可选节点，仅在 plan_post_commit 检测到 ARC_END 信号时被调度执行。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，更新 state["out_lines"] 并 pop pending_actions
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        out_lines = list(state.get("out_lines") or [])
        result = save_arc_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines)
        if result is None:
            _append_line(state, "[warn] arc_summary_followup returned None")
        state["out_lines"] = out_lines
        _pop_pending_action(state)
        return state

    return _node


def volume_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建卷摘要保存节点工厂函数。

    调用 review_flow.save_volume_summary_followup 保存当前卷的摘要信息，
    使用 always=True 强制忽略频率限制（由 volume_summary_node 自行控制频率）。

    与 arc_summary_node 类似，但频率更低（每卷结束时一次），且依赖 progress.current_volume
    确定当前卷号。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，更新 state["out_lines"] 并 pop pending_actions
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        progress = runtime.store.progress.load()
        volume = max(1, progress.current_volume) if progress else 1
        out_lines = list(state.get("out_lines") or [])
        result = save_volume_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines, volume=volume, always=True)
        if result is None:
            _append_line(state, "[warn] volume_summary_followup returned None")
        state["out_lines"] = out_lines
        _pop_pending_action(state)
        return state

    return _node


def expand_arc_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建大纲扩展节点工厂函数。

    处理长篇小说的分层大纲扩展，支持两种模式：
    - expand_arc：在当前卷内扩展下一弧（需要分层大纲中已定义目标弧）
    - append_volume：追加全新的一卷（目标弧不存在或非分层大纲模式）

    通过 LLM 调用 generate_longform_outline_payload 生成大纲内容，
    再通过 save_foundation 工具持久化到存储层。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，调用 save_foundation 后 pop pending_actions
    """
    def _node(state: GraphState) -> GraphState:
        _execute_expand_arc_safe(runtime, state)
        _pop_pending_action(state)
        return state

    return _node


def _execute_expand_arc_safe(
    runtime: "LangGraphRuntime",
    state: GraphState,
    out_lines: list[str] | None = None,
) -> None:
    """expand_arc 任务的安全执行函数（优化 ①-1：供 _run_summary_task 在线程中调用）。

    与 expand_arc_node 的内部逻辑一致，但接受外部 out_lines 列表以避免与主流程冲突。
    若 out_lines 为 None，则将日志直接追加到 state["out_lines"]。
    """
    chapter = int(state.get("current_chapter") or 1)
    client = runtime.build_client()
    progress = runtime.store.progress.load()
    architect = runtime.get_agent("architect")
    planning_tier = architect.effective_planning_tier()
    foundation_type = "append_volume"
    payload = None
    if progress and progress.layered:
        volumes = runtime.store.outline.load_layered_outline()
        current_volume = max(1, progress.current_volume or 1)
        current_arc = max(1, progress.current_arc or 1)
        target_arc = current_arc + 1
        has_target_arc = False
        for vol in volumes:
            if vol.index == current_volume:
                has_target_arc = any(arc.index == target_arc for arc in vol.arcs)
                break
        if has_target_arc:
            foundation_type = "expand_arc"
            payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "expand_arc")
    if payload is None:
        payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "append_volume")
    runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation {foundation_type} (ch{chapter})", level="info"))
    if foundation_type == "expand_arc":
        runtime.runner.call_tool(
            "save_foundation",
            {"type": "expand_arc", "volume": progress.current_volume if progress else 1, "arc": (progress.current_arc or 1) + 1 if progress else 2, "content": payload.get("chapters", [])},
        )
    else:
        runtime.runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})
    log_line = f"[tool] save_foundation -> {foundation_type}"
    if out_lines is not None:
        out_lines.append(log_line)
    else:
        _append_line(state, log_line)

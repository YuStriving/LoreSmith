from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.agents.hints import HintAction
from ainovel_py.agents.longform import generate_longform_outline_payload
from ainovel_py.agents.post_commit import plan_post_commit, plan_review_followup
from ainovel_py.agents.review_flow import save_arc_summary_followup, save_volume_summary_followup
from ainovel_py.agents.runner import (
    _extract_commit_metadata,
    _generate_review_payload,
    _run_write_commit_cycle,
)

from ..actions import plan_actions
from ainovel_py.domain.runtime import FlowState
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event

from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


MAX_STEPS = 12


def _append_line(state: GraphState, line: str) -> None:
    lines = list(state.get("out_lines") or [])
    lines.append(line)
    state["out_lines"] = lines


def _set_pending_actions(state: GraphState, actions: list[str]) -> None:
    state["pending_actions"] = actions
    state["pending_action"] = actions[0] if actions else "checkpoint"


def _pop_pending_action(state: GraphState) -> None:
    actions = list(state.get("pending_actions") or [])
    if actions:
        actions.pop(0)
    state["pending_actions"] = actions
    state["pending_action"] = actions[0] if actions else "checkpoint"


def _enqueue_hint_actions(state: GraphState, actions: list[HintAction]) -> str:
    plan = plan_actions(actions)
    _set_pending_actions(state, list(plan.queue))
    if plan.queue:
        _append_line(state, "[hint-actions] " + ", ".join(plan.queue))
    return plan.next_action


def load_runtime_context(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        pending = runtime.store.signals.load_pending_commit()
        pending_checkpoint = runtime.store.signals.load_pending_checkpoint()
        latest = runtime.store.checkpoints.latest_global()
        current_chapter = progress.next_chapter() if progress else 1
        next_action = "novel_context"
        rewrite_mode = ""
        seed_text = str(state.get("seed_text") or "").strip()
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            current_chapter = progress.pending_rewrites[0]
            rewrite_mode = "polish" if progress.flow == FlowState.POLISHING else "rewrite"
        if pending_checkpoint is not None:
            current_chapter = pending_checkpoint.next_chapter
            if seed_text == "__RUN_CONTINUE__":
                runtime.store.signals.clear_pending_checkpoint()
                next_action = "novel_context"
                _append_line(state, f"[run] confirmation accepted -> next_chapter={pending_checkpoint.next_chapter}")
            else:
                next_action = "finish"
                _append_line(state, f"[resume] awaiting_confirmation -> pause_after={pending_checkpoint.pause_after_chapter}")
        elif state.get("resume_mode"):
            if pending is not None:
                current_chapter = pending.chapter
                next_action = "commit_chapter"
                _append_line(state, f"[resume] pending_commit -> chapter={pending.chapter} stage={pending.stage}")
            elif progress and progress.in_progress_chapter > 0:
                current_chapter = progress.in_progress_chapter
                step = latest.step if latest and latest.scope.kind == "chapter" and latest.scope.chapter == current_chapter else ""
                if step == "consistency_check":
                    next_action = "commit_chapter"
                elif step == "draft":
                    next_action = "commit_chapter"
                elif step == "plan":
                    next_action = "generate_draft"
                else:
                    next_action = "novel_context"
                _append_line(state, f"[resume] in_progress -> chapter={current_chapter} step={step or 'unknown'}")
            elif progress and progress.pending_rewrites:
                current_chapter = progress.pending_rewrites[0]
                next_action = rewrite_mode or "rewrite"
                _append_line(state, f"[resume] rewrite_queue -> chapter={current_chapter} mode={rewrite_mode or 'rewrite'}")
        state["current_chapter"] = current_chapter
        state["progress_snapshot"] = {
            "phase": progress.phase if progress else "",
            "flow": progress.flow if progress else "",
            "total_chapters": progress.total_chapters if progress else 0,
            "completed_chapters": list(progress.completed_chapters) if progress else [],
            "pending_rewrites": list(progress.pending_rewrites) if progress else [],
            "rewrite_reason": progress.rewrite_reason if progress else "",
            "in_progress_chapter": progress.in_progress_chapter if progress else 0,
        }
        state["pending_review_for"] = None
        state["rewrite_mode"] = rewrite_mode
        state["pending_actions"] = []
        state["pending_action"] = next_action
        return state

    return _node


def novel_context_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        progress = runtime.store.progress.load()
        context = runtime.runner.call_tool("novel_context", {"chapter": chapter})
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            context = runtime._build_rewrite_context(progress, context)
        state["context"] = context
        return state

    return _node


def plan_chapter_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = state.get("context") or {}
        seed_text = str(state.get("seed_text") or "")
        progress = runtime.store.progress.load()
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            summary = f"调用 plan_chapter (rewrite ch{chapter})"
        else:
            summary = f"调用 plan_chapter (ch{chapter})"
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=summary, level="info"))
        plan_payload = runtime._build_dynamic_plan(seed_text, chapter, context)
        plan_res = runtime.runner.call_tool("plan_chapter", plan_payload)
        latest_plan = plan_res.get("plan") or plan_payload
        state["latest_plan"] = latest_plan
        state["pending_action"] = "generate_draft"
        return state

    return _node


def generate_draft_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        client = runtime.build_client()
        context = state.get("context") or {}
        plan = state.get("latest_plan") or {}
        contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}
        draft, word_count = runtime._generate_chapter_with_context(
            client=client,
            seed_text=str(state.get("seed_text") or ""),
            chapter=chapter,
            context=context,
            plan=plan,
            contract=contract,
        )
        state["latest_draft"] = draft
        _append_line(state, f"[tool] draft_generation -> word_count={word_count}")
        return state

    return _node


def commit_chapter_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        client = runtime.build_client()
        chapter = int(state.get("current_chapter") or 1)
        draft = str(state.get("latest_draft") or "")
        if not draft:
            draft = runtime.store.drafts.load_draft(chapter)
        if not draft:
            raise RuntimeError(f"chapter {chapter} draft is empty")
        metadata = _extract_commit_metadata(client, chapter, draft)
        summary = str(metadata.get("summary", "") or runtime._summarize_chapter(client, chapter, draft))
        draft_res, commit_res = _run_write_commit_cycle(runtime.runner, runtime.emit_event, chapter, draft, summary, metadata)
        state["latest_commit_result"] = commit_res
        _append_line(state, f"[tool] plan_chapter -> chapter={chapter}")
        _append_line(state, f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
        _append_line(state, f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")
        plan = plan_post_commit(commit_res, chapter)
        if plan.hints:
            _append_line(state, "[hints] " + " | ".join(plan.hints))
        next_action = _enqueue_hint_actions(state, plan.actions)
        state["pending_review_for"] = plan.pending_review_for
        state["pending_action"] = next_action if plan.next_action == next_action or next_action != "checkpoint" else plan.next_action
        return state

    return _node


def review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("pending_review_for") or 0)
        if chapter <= 0:
            state["pending_action"] = "checkpoint"
            return state
        client = runtime.build_client()
        review_payload = _generate_review_payload(client, runtime.runner, chapter)
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = runtime.runner.call_tool("save_review", review_payload)
        state["latest_review_result"] = review_res
        _append_line(state, f"[tool] save_review -> final_verdict={review_res.get('final_verdict', '')}")
        plan = plan_review_followup(review_res)
        next_action = _enqueue_hint_actions(state, plan.actions) if plan.actions else plan.next_action
        state["pending_review_for"] = None
        state["pending_action"] = next_action
        return state

    return _node


def rewrite_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
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


def arc_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        out_lines = list(state.get("out_lines") or [])
        save_arc_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines)
        state["out_lines"] = out_lines
        _pop_pending_action(state)
        return state

    return _node


def volume_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        progress = runtime.store.progress.load()
        volume = max(1, progress.current_volume) if progress else 1
        out_lines = list(state.get("out_lines") or [])
        save_volume_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines, volume=volume, always=True)
        state["out_lines"] = out_lines
        _pop_pending_action(state)
        return state

    return _node


def expand_arc_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        client = runtime.build_client()
        progress = runtime.store.progress.load()
        planning_tier = runtime._effective_planning_tier()
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
                payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "expand_arc")
                runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation expand_arc (ch{chapter})", level="info"))
                runtime.runner.call_tool(
                    "save_foundation",
                    {"type": "expand_arc", "volume": current_volume, "arc": target_arc, "content": payload.get("chapters", [])},
                )
                _append_line(state, "[tool] save_foundation -> expand_arc")
            else:
                payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "append_volume")
                runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation append_volume (ch{chapter})", level="info"))
                runtime.runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})
                _append_line(state, "[tool] save_foundation -> append_volume")
        else:
            payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "append_volume")
            runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation append_volume (ch{chapter})", level="info"))
            runtime.runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})
            _append_line(state, "[tool] save_foundation -> append_volume")
        _pop_pending_action(state)
        return state

    return _node


def checkpoint_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
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
        if steps >= MAX_STEPS or runtime._aborted:
            state["pending_action"] = "finish"
            return state
        next_chapter = progress.next_chapter() if progress else chapter + 1
        if steps > 0 and steps % 5 == 0:
            pending = PendingRunCheckpoint(
                pause_after_chapter=max(completed) if completed else chapter,
                next_chapter=next_chapter,
                completed_count=steps,
            )
            runtime.store.signals.save_pending_checkpoint(pending)
            runtime.emit_checkpoint_pending(pending)
            state["current_chapter"] = next_chapter
            state["pending_action"] = "finish"
            return state
        state["current_chapter"] = next_chapter
        state["pending_action"] = "continue"
        return state

    return _node


def finish_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        state["pending_action"] = "finish"
        return state

    return _node


def route_after_load(state: GraphState) -> str:
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
    action = str(state.get("pending_action") or "generate_draft")
    if action == "finish":
        return "finish"
    return "generate_draft"


def route_after_commit(state: GraphState) -> str:
    action = str(state.get("pending_action") or "checkpoint")
    if action == "review":
        return "review"
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "arc_summary":
        return "arc_summary"
    if action == "volume_summary":
        return "volume_summary"
    if action == "expand_arc":
        return "expand_arc"
    if action == "finish":
        return "finish"
    return "checkpoint"


def route_after_checkpoint(state: GraphState) -> str:
    action = str(state.get("pending_action") or "finish")
    if action == "novel_context" or action == "continue":
        return "novel_context"
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "arc_summary":
        return "arc_summary"
    if action == "volume_summary":
        return "volume_summary"
    if action == "expand_arc":
        return "expand_arc"
    return "finish"

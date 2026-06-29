from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
import json
from typing import Any, Callable
from ainovel_py.agents.hints import has_placeholder_action
from ainovel_py.agents.longform import run_longform_hint_actions
from ainovel_py.agents.post_commit import plan_post_commit, plan_review_followup
from ainovel_py.agents.review_flow import save_arc_summary_followup, save_volume_summary_followup
from ainovel_py.domain.runtime import FlowState, infer_planning_tier, normalize_planning_tier
from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.orchestrator.interface import OrchestratorBackend
from ainovel_py.assets import load_bundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.writing import ChapterContract, ChapterPlan
from ainovel_py.host.events import Event
@dataclass
class AgentRunner:
    tools: dict[str, object]
    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"tool not found: {name}")
        return tool.execute(args)
class LLMCoordinatorBackend:
    def __init__(
        self,
        cfg: Config,
        runner: AgentRunner,
        store: Any,
        emit_event: Callable[[Event], None],
        emit_stream: Callable[[str, str], None],
    ) -> None:
        self.cfg = cfg
        self.runner = runner
        self.store = store
        self.emit_event = emit_event
        self.emit_stream = emit_stream
        self._aborted = False
        self.context_manager = ContextManager(context_window=cfg.context_window)
        self.assets = load_bundle(cfg.style)
    def start(self, prompt: str) -> None:
        self._aborted = False
        self._run_loop(prompt)
    def resume(self, prompt: str) -> None:
        self._aborted = False
        self._run_loop(prompt)
    def follow_up(self, text: str) -> None:
        self._aborted = False
        self._run_loop(text)
    def abort(self) -> None:
        self._aborted = True
    def wait_idle(self) -> None:
        return
    def _run_loop(self, seed_text: str) -> None:
        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 未配置")
        key_norm = pc.api_key.strip().lower()
        if key_norm in {"dummy-key", "dummy", "test", "placeholder", "changeme"}:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 为占位值")
        client = OpenAICompatClient(
            api_key=pc.api_key,
            model=self.cfg.model,
            base_url=pc.base_url,
            timeout=120.0,
        )
        out_lines = [f"[Python Port] LLM协调器开始执行：{seed_text}"]
        steps = 0
        max_steps = 12
        pending_review_for: int | None = None
        while not self._aborted and steps < max_steps:
            progress = self.store.progress.load()
            if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
                chapter = progress.pending_rewrites[0]
                context = self.runner.call_tool("novel_context", {"chapter": chapter})
                rewrite_context = self._build_rewrite_context(progress, context)
                plan_payload = self._build_dynamic_plan(seed_text, chapter, rewrite_context)
                self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 plan_chapter (rewrite ch{chapter})", level="info"))
                plan_res = self.runner.call_tool("plan_chapter", plan_payload)
                plan = plan_res.get("plan") or plan_payload
                contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}
                draft, _ = self._generate_chapter_with_context(client, seed_text, chapter, context, plan, contract)
                metadata = _extract_commit_metadata(client, chapter, draft)
                summary = str(metadata.get("summary", "") or self._summarize_chapter(client, chapter, draft))
                draft_res, commit_res = _run_write_commit_cycle(self.runner, self.emit_event, chapter, draft, summary, metadata)
                out_lines.append(f"[tool] rewrite_chapter -> chapter={chapter}")
                out_lines.append(f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
                out_lines.append(f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")
                hints = commit_res.get("system_hints") or []
                if hints:
                    out_lines.append("[hints] " + " | ".join(hints))
                steps += 1
                continue
            if pending_review_for is not None:
                review_chapter = pending_review_for
                review_result = _run_review_summary(client, self.runner, self.emit_event, review_chapter, out_lines)
                pending_review_for = None
                plan = plan_review_followup(review_result)
                if plan.hints:
                    out_lines.append("[hints] " + " | ".join(plan.hints))
                if has_placeholder_action(plan.actions):
                    run_longform_hint_actions(
                        client,
                        self.runner,
                        self.emit_event,
                        self.assets,
                        self._effective_planning_tier(),
                        review_chapter,
                        plan.actions,
                        out_lines,
                    )
                steps += 1
                continue
            chapter = progress.next_chapter() if progress else 1
            if progress and progress.total_chapters > 0 and chapter > progress.total_chapters:
                break
            context = self.runner.call_tool("novel_context", {"chapter": chapter})
            plan_payload = self._build_dynamic_plan(seed_text, chapter, context)
            self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 plan_chapter (ch{chapter})", level="info"))
            plan_res = self.runner.call_tool("plan_chapter", plan_payload)
            plan = plan_res.get("plan") or plan_payload
            contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}
            draft, _ = self._generate_chapter_with_context(
                client=client,
                seed_text=seed_text,
                chapter=chapter,
                context=context,
                plan=plan,
                contract=contract,
            )
            metadata = _extract_commit_metadata(client, chapter, draft)
            summary = str(metadata.get("summary", "") or self._summarize_chapter(client, chapter, draft))
            draft_res, commit_res = _run_write_commit_cycle(self.runner, self.emit_event, chapter, draft, summary, metadata)
            out_lines.append(f"[tool] plan_chapter -> chapter={chapter}")
            out_lines.append(f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
            out_lines.append(f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")
            plan = plan_post_commit(commit_res, chapter)
            if plan.pending_review_for is not None:
                pending_review_for = plan.pending_review_for
            else:
                if plan.hints:
                    out_lines.append("[hints] " + " | ".join(plan.hints))
                if has_placeholder_action(plan.actions):
                    out_lines.append("[hint-actions] " + ", ".join(a.value for a in plan.actions))
            steps += 1
        self.emit_stream("thinking", "\n".join(out_lines) + "\n")
    def _build_rewrite_context(self, progress: Any, context: dict[str, Any]) -> dict[str, Any]:
        merged = dict(context)
        latest_review = context.get("latest_review") or {}
        if progress and progress.rewrite_reason:
            merged["rewrite_reason"] = progress.rewrite_reason
        if latest_review:
            merged["rewrite_issues"] = latest_review.get("issues") or []
        return merged
    def _build_dynamic_plan(self, seed_text: str, chapter: int, context: dict[str, Any], feedback: str = "") -> dict[str, Any]:
        outline = context.get("current_chapter_outline") or {}
        latest_review = context.get("latest_review") or {}
        recent_summaries = context.get("recent_summaries") or []
        review_focus: list[str] = []
        if isinstance(latest_review, dict):
            for issue in latest_review.get("issues") or []:
                desc = str(issue.get("description", "") or "").strip()
                if desc:
                    review_focus.append(desc)
        character_names = [
            str(item.get("name", "") or "").strip()
            for item in (context.get("characters") or [])
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        ]
        summary_focus = [str(item.get("summary", "") or "") for item in recent_summaries if isinstance(item, dict)]
        rewrite_reason = str(context.get("rewrite_reason", "") or "")
        rewrite_issues = [
            str(item.get("description", "") or "")
            for item in (context.get("rewrite_issues") or [])
            if isinstance(item, dict)
        ]
        core_event = str(outline.get("core_event", "") or "推进主线冲突").strip()
        hook = str(outline.get("hook", "") or "让局面出现新的不确定性").strip()
        previous_landing = ""
        if recent_summaries:
            latest_summary = recent_summaries[-1]
            if isinstance(latest_summary, dict):
                previous_landing = str(latest_summary.get("emotional_landing", "") or "").strip()
        payoff_hint = summary_focus[-1] if summary_focus else ""
        direction_parts = [f"本章围绕“{core_event}”展开"]
        if payoff_hint:
            direction_parts.append(f"承接前文余波：{payoff_hint[:80]}")
        direction_parts.append(f"结尾把读者推向“{hook}”")
        chapter_direction = "；".join(direction_parts) + "。"
        emotion_target = "让读者先感到角色被局面逼近，再在细节变化里意识到问题变得更棘手。"
        if previous_landing:
            emotion_target = f"承接上一章“{previous_landing}”的余韵，" + emotion_target
        meta = self.store.run_meta.load()
        min_words_default = meta.min_words if meta else 1200
        target_words_default = meta.target_words if meta else 1800
        max_words_default = meta.max_words if meta else 2600
        avoid = ["不要提前完结主线", "不要无铺垫引入重大设定变更"]
        if rewrite_reason:
            avoid = [rewrite_reason[:80], avoid[0]]
        elif rewrite_issues:
            avoid = [x[:80] for x in rewrite_issues[:2]]
        continuity_checks = review_focus[:2] + rewrite_issues[:1]
        if character_names:
            continuity_checks.append("沿用已有人物姓名和称谓，不要创造同位替身角色")
        contract = {
            "chapter_direction": chapter_direction,
            "required_beats": [],
            "avoid": avoid[:2],
            "forbidden_moves": avoid[:2],
            "continuity_checks": continuity_checks[:3],
            "evaluation_focus": [],
            "emotion_target": emotion_target,
            "payoff_points": summary_focus[-1:],
            "hook_goal": hook,
            "min_words": min_words_default,
            "target_words": target_words_default,
            "max_words": max_words_default,
        }
        base_plan = {
            "chapter": chapter,
            "title": str(outline.get("title", "") or f"第{chapter}章"),
            "goal": core_event,
            "conflict": core_event or "角色在压力中做出高代价选择",
            "hook": hook,
            "emotion_arc": emotion_target,
            "notes": f"seed={seed_text[:80]} | rewrite_reason={rewrite_reason[:120]}",
            "contract": contract,
        }
        if feedback:
            revised = self._revise_plan_with_feedback(seed_text, chapter, context, base_plan, feedback)
            if revised:
                return revised
            base_plan["notes"] = (str(base_plan.get("notes", "") or "") + f" | feedback={feedback[:120]}").strip()
        return base_plan
    def _revise_plan_with_feedback(
        self,
        seed_text: str,
        chapter: int,
        context: dict[str, Any],
        base_plan: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any] | None:
        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            return None
        try:
            client = OpenAICompatClient(api_key=pc.api_key, model=self.cfg.model, base_url=pc.base_url, timeout=120.0)
            pack = self.context_manager.build_writer_pack(context)
            system_prompt = "你是小说章节规划助手，只输出 JSON。请基于既有章节上下文和用户反馈，返回修订后的本章计划。"
            prompt = (
                f"请修订第{chapter}章计划，严格输出 JSON 对象，字段必须包含：chapter,title,goal,conflict,hook,emotion_arc,notes,contract。"
                f"contract 内字段：chapter_direction,avoid,continuity_checks,emotion_target,hook_goal,min_words,target_words,max_words。"
                f"如需兼容可保留 required_beats/forbidden_moves/payoff_points，但不要把它们写成任务清单。\n\n"
                f"[用户方向]\n{seed_text}\n\n"
                f"[用户反馈]\n{feedback}\n\n"
                f"[当前计划]\n{json.dumps(base_plan, ensure_ascii=False)}\n\n"
                f"{pack.summary_block or ''}"
            )
            raw = client.complete(system_prompt, prompt, temperature=0.4)
            data = json.loads(raw)
            plan = self._chapter_plan_to_dict(self._dict_to_chapter_plan(data))
            plan["notes"] = (str(plan.get("notes", "") or "") + f" | feedback={feedback[:120]}").strip()
            return plan
        except Exception:
            return None
    @staticmethod
    def _dict_to_chapter_plan(data: dict[str, Any]) -> ChapterPlan:
        contract_data = data.get("contract") or {}
        return ChapterPlan(
            chapter=int(data.get("chapter", 0) or 0),
            title=str(data.get("title", "") or ""),
            goal=str(data.get("goal", "") or ""),
            conflict=str(data.get("conflict", "") or ""),
            hook=str(data.get("hook", "") or ""),
            emotion_arc=str(data.get("emotion_arc", "") or ""),
            notes=str(data.get("notes", "") or ""),
            contract=ChapterContract(
                chapter_direction=str(contract_data.get("chapter_direction", "") or ""),
                required_beats=[str(x) for x in (contract_data.get("required_beats") or [])],
                avoid=[str(x) for x in (contract_data.get("avoid") or [])],
                forbidden_moves=[str(x) for x in (contract_data.get("forbidden_moves") or [])],
                continuity_checks=[str(x) for x in (contract_data.get("continuity_checks") or [])],
                evaluation_focus=[str(x) for x in (contract_data.get("evaluation_focus") or [])],
                emotion_target=str(contract_data.get("emotion_target", "") or ""),
                payoff_points=[str(x) for x in (contract_data.get("payoff_points") or [])],
                hook_goal=str(contract_data.get("hook_goal", "") or ""),
                min_words=int(contract_data.get("min_words", 1200) or 1200),
                target_words=int(contract_data.get("target_words", 1800) or 1800),
                max_words=int(contract_data.get("max_words", 2600) or 2600),
            ),
        )
    @staticmethod
    def _chapter_plan_to_dict(plan: ChapterPlan) -> dict[str, Any]:
        return asdict(plan)
    def _generate_chapter_with_context(
        self,
        client: OpenAICompatClient,
        seed_text: str,
        chapter: int,
        context: dict[str, Any],

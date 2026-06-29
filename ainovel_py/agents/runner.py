from __future__ import annotations

from typing import Any

from ainovel_py.domain.writing import ChapterContract, ChapterPlan


class AgentRunner:

    def __init__(self, tools: dict[str, object]) -> None:
        self.tools = tools

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"tool not found: {name}")
        return tool.execute(args)


def dict_to_chapter_plan(data: dict[str, Any]) -> ChapterPlan:
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
            required_beats=[str(x) for x in (contract_data.get("required_beats") or [])],
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


def chapter_plan_to_dict(plan: ChapterPlan) -> dict[str, Any]:
    from dataclasses import asdict
    return asdict(plan)

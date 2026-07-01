from __future__ import annotations

import json
import os
import time
import urllib.error
from datetime import datetime
from typing import Any

from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.assets import load_bundle
from ainovel_py.host.events import Event

from .base import BaseAgent


os.environ.setdefault("AINOVEL_HTTP_TIMEOUT", "30")


_FALLBACK_DIMENSION_SCORES: list[dict[str, Any]] = [
    {"dimension": "consistency", "score": 85, "verdict": "pass", "comment": "设定一致"},
    {"dimension": "character", "score": 82, "verdict": "pass", "comment": "角色动机成立"},
    {"dimension": "pacing", "score": 78, "verdict": "warning", "comment": "中段可压缩"},
    {"dimension": "continuity", "score": 86, "verdict": "pass", "comment": "连续性良好"},
    {"dimension": "foreshadow", "score": 80, "verdict": "pass", "comment": "伏笔明确"},
    {"dimension": "hook", "score": 83, "verdict": "pass", "comment": "钩子有效"},
    {"dimension": "aesthetic", "score": 81, "verdict": "pass", "comment": "语言风格稳定"},
]

# ── 评审维度权重（防 review↔rewrite 死循环） ──────────────────────
# 核心思路：不是所有维度都一样重要。"人设一致性"比"语言风格"关键得多，
# 所以 consistency 权重 25%，aesthetic 权重 10%。
# 当加权总分 >= PASS_THRESHOLD 时，即使个别维度 fail，也直接放行。
REVIEW_DIMENSION_WEIGHTS: dict[str, float] = {
    "consistency": 0.25,   # 人设一致性（最关键：主角性格突变、设定矛盾是致命伤）
    "continuity": 0.20,   # 连续性（剧情衔接断裂读者会出戏）
    "pacing":      0.15,   # 节奏（剧情推进节奏）
    "character":   0.10,   # 角色（角色动机和成长弧）
    "foreshadow":  0.10,   # 伏笔（伏笔埋设与回收）
    "hook":        0.10,   # 钩子（章末钩子效果）
    "aesthetic":   0.10,   # 美学（语言风格和文笔）
}

REVIEW_PASS_THRESHOLD = 75       # 加权总分 >= 75 直接 accept
MAX_REWRITE_ATTEMPTS = 5         # 最多重写 5 次（兜底）
MAX_STAGNANT_REWRITES = 2        # 连续 2 次总分未改善 → 强制 accept


def compute_weighted_score(
    dimensions: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> float:
    """计算评审维度的加权总分。

    Args:
        dimensions: LLM 返回的维度评分列表，每项含 dimension + score
        weights: 权重字典，默认使用 REVIEW_DIMENSION_WEIGHTS

    Returns:
        加权总分（0-100，保留1位小数）
    """
    if weights is None:
        weights = REVIEW_DIMENSION_WEIGHTS
    total = 0.0
    for dim in dimensions:
        name = dim.get("dimension", "")
        score = float(dim.get("score", 0))
        weight = weights.get(name, 0.0)
        total += score * weight
    return round(total, 1)


def _call_with_retry(
    client: OpenAICompatClient,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_attempts: int = 2,
) -> str:
    """

    捕获可重试错误：超时、网络中断、5xx；其他异常（如 JSON 解析失败）直接抛出。
    重试间隔 1s（指数退避起点）。
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return client.complete(system_prompt, user_prompt, temperature)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_exc = exc
            if attempt + 1 < max_attempts:
                time.sleep(1.0)
    assert last_exc is not None
    raise last_exc


class EditorAgent(BaseAgent):
    """小说编辑评审 Agent。

    职责：
    - execute(chapter) → LLM 评审 + save_review 落盘
    - extract_metadata(chapter, draft) → LLM 抽取结构化 metadata（与 metadata_extractor 协作）
    - run_write_commit_cycle(...) → 写稿 → 一致性检查 → 提交三步

    防御策略：
    - LLM 返回非 JSON 时使用 is_fallback 标记 + emit_event WARN，调用方可感知降级
    - LLM 调用统一 30s timeout + 1 次重试（_call_with_retry）
    - chapter 字段 setdefault 不覆盖 LLM 返回值
    """

    name = "editor"
    model_capability = "review"      # 阶段 D：按 capability 选模型（editor_commit / editor_review 共享实例）

    def system_prompt(self) -> str:
        return self.assets.prompts.get("editor") or "你是严格的小说编辑评审助手，只输出 JSON。"

    def execute(self, *, chapter: int) -> dict[str, Any]:
        client = self.build_client()
        review_payload = self._generate_review_payload(client, chapter)
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = self.runner.call_tool("save_review", review_payload)
        return {"review": review_res, "review_payload": review_payload, "chapter": chapter}

    def extract_metadata(self, *, chapter: int, draft: str) -> dict[str, Any]:
        client = self.build_client()
        return self._extract_commit_metadata(client, chapter, draft)

    def run_write_commit_cycle(
        self,
        chapter: int,
        draft: str,
        summary: str,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 draft_chapter (ch{chapter})", level="info"))
        draft_res = self.runner.call_tool("draft_chapter", {"chapter": chapter, "content": draft, "mode": "write"})
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 check_consistency (ch{chapter})", level="info"))
        self.runner.call_tool("check_consistency", {"chapter": chapter})
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 commit_chapter (ch{chapter})", level="info"))
        commit_res = self.runner.call_tool(
            "commit_chapter",
            {
                "chapter": chapter,
                "summary": summary,
                "characters": metadata.get("characters") or ["主角"],
                "key_events": metadata.get("key_events") or [f"第{chapter}章推进"],
                "timeline_events": metadata.get("timeline_events") or [],
                "foreshadow_updates": metadata.get("foreshadow_updates") or [],
                "relationship_changes": metadata.get("relationship_changes") or [],
                "state_changes": metadata.get("state_changes") or [],
                "hook_type": metadata.get("hook_type") or "mystery",
                "dominant_strand": metadata.get("dominant_strand") or "quest",
            },
        )
        return draft_res, commit_res

    def _extract_commit_metadata(self, client: OpenAICompatClient, chapter: int, draft: str) -> dict[str, Any]:
        prompt = f"""
请从下面的第{chapter}章正文中提取结构化信息，并严格输出 JSON 对象（不要输出 Markdown、不要解释）。
字段要求：
- summary: 字符串
- characters: 字符串数组
- key_events: 字符串数组
- timeline_events: 对象数组，每项 {{"time": 字符串, "event": 字符串, "characters": 字符串数组}}
- foreshadow_updates: 对象数组，每项 {{"id": 字符串, "action": "plant"|"advance"|"resolve", "description": 字符串}}
  - action=plant 时 description 必填，id 必须稳定可复用（如 fs_clue_01）
- relationship_changes: 对象数组，每项 {{"character_a": 字符串, "character_b": 字符串, "relation": 字符串, "chapter": 数字}}
  - character_a / character_b / relation 都不能为空
- state_changes: 对象数组，每项 {{"entity": 字符串, "field": 字符串, "old_value": 字符串, "new_value": 字符串, "reason": 字符串, "chapter": 数字}}
- hook_type: 字符串
- dominant_strand: 字符串

如果某项不存在请返回空数组，不要伪造空对象。

正文：
{draft}
""".strip()
        raw = _call_with_retry(
            client,
            "你是小说信息抽取助手，只输出 JSON。\n" + (load_bundle("default").references.get("consistency") or ""),
            prompt,
            temperature=0.2,
        )
        try:
            data = json.loads(raw)
            data.setdefault("chapter", chapter)
            data["is_fallback"] = False
        except Exception as exc:
            # P1 修复：fallback 时 emit_event WARN，调用方通过 is_fallback 标记感知降级
            self.emit_event(Event(
                time=datetime.now(),
                category="AGENT",
                summary=f"EditorAgent: ch{chapter} metadata JSON 解析失败，使用兜底。原因: {type(exc).__name__}: {exc}",
                level="warn",
            ))
            try:
                summary_fallback = _call_with_retry(
                    client,
                    "你是摘要助手。",
                    f"请用一到两句话总结第{chapter}章的关键推进、冲突变化和章末悬念，控制在80字以内。\n\n{draft}",
                    temperature=0.3,
                )
            except Exception as exc2:
                self.emit_event(Event(
                    time=datetime.now(),
                    category="AGENT",
                    summary=f"EditorAgent: ch{chapter} summary 二次 LLM 也失败: {type(exc2).__name__}: {exc2}",
                    level="warn",
                ))
                summary_fallback = ""
            data = {
                "chapter": chapter,
                "summary": summary_fallback,
                "characters": ["主角"],
                "key_events": [f"第{chapter}章推进"],
                "timeline_events": [],
                "foreshadow_updates": [],
                "relationship_changes": [],
                "state_changes": [],
                "hook_type": "mystery",
                "dominant_strand": "quest",
                "is_fallback": True,
                "_fallback_reason": f"{type(exc).__name__}: {exc}",
            }
        return data

    def _generate_review_payload(self, client: OpenAICompatClient, chapter: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if context is None:
            context = self.runner.call_tool("novel_context", {"chapter": chapter})
        draft_read = self.runner.call_tool("read_chapter", {"chapter": chapter, "source": "draft"})
        draft = str(draft_read.get("content", "") or "")
        prompt = f"""
请以小说编辑身份审阅第{chapter}章，并严格输出 JSON 对象，字段包括：
chapter, scope, dimensions, issues, contract_status, contract_misses, contract_notes, verdict, summary, affected_chapters。
其中：
- dimensions 必须包含 consistency, character, pacing, continuity, foreshadow, hook, aesthetic 七个维度；
- 每个维度包含 dimension, score(0-100), verdict(pass/warning/fail), comment；
- issues 每项包含 type, severity, description, evidence, suggestion；
- verdict 只能是 accept/polish/rewrite。

[章节正文]
{draft}

[章节上下文]
{context}
""".strip()
        raw = _call_with_retry(
            client,
            (load_bundle("default").prompts.get("editor") or "你是严格的小说编辑评审助手，只输出 JSON。"),
            prompt,
            temperature=0.2,
        )
        try:
            data = json.loads(raw)
            data.setdefault("chapter", chapter)
            data.setdefault("scope", "chapter")
            data["is_fallback"] = False
            data["_weighted_score"] = compute_weighted_score(data.get("dimensions", []))
        except Exception as exc:
            # P1 修复：评审 fallback 同样 emit_event WARN
            self.emit_event(Event(
                time=datetime.now(),
                category="AGENT",
                summary=f"EditorAgent: ch{chapter} review JSON 解析失败，使用兜底 polish。原因: {type(exc).__name__}: {exc}",
                level="warn",
            ))
            data = {
                "chapter": chapter,
                "scope": "chapter",
                "dimensions": [dict(d) for d in _FALLBACK_DIMENSION_SCORES],
                "issues": [
                    {
                        "type": "pacing",
                        "severity": "warning",
                        "description": "中段说明略长",
                        "evidence": "第二段连续解释较多",
                        "suggestion": "压缩背景说明",
                    }
                ],
                "contract_status": "met",
                "contract_misses": [],
                "contract_notes": "核心契约已满足（兜底）",
                "verdict": "polish",          # 改为 polish：fallback 时至少触发一次轻修，不直接 accept
                "summary": "LLM 返回格式异常，触发轻修（兜底）",
                "affected_chapters": [],
                "is_fallback": True,
                "_fallback_reason": f"{type(exc).__name__}: {exc}",
                "_weighted_score": compute_weighted_score(_FALLBACK_DIMENSION_SCORES),
            }
        return data

    def generate_review_payload(self, client: OpenAICompatClient, chapter: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._generate_review_payload(client, chapter, context)

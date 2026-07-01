from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.domain.runtime import Progress
from ainovel_py.host.events import Event

# P1 修复：复用 editor.py 的 _call_with_retry helper（30s timeout + 1 次重试）
from ainovel_py.agents.roles.editor import _call_with_retry

from .base import BaseAgent


class RewriteAgent(BaseAgent):
    """小说重写 Agent。

    职责：
    - build_rewrite_context(progress, context) → 注入了评审意见和重写原因的 context
      （真在用：context_nodes.py:109, helpers.py:119）
    - execute(chapter, context, review_result, rewrite_mode) → LLM 生成重写文本 +
      draft_chapter 工具落盘

    P0 修复（review/rewrite-audit/code-review-report.md）：execute() 补 LLM 调用 + 落盘闭环。
    """

    name = "rewrite"
    model_capability = "longform"    # 阶段 D：按 capability 选模型（与 writer 一致）

    def system_prompt(self) -> str:
        return self.assets.prompts.get("rewrite") or self.assets.prompts.get("editor") or "你是小说重写助手，根据评审意见重写章节正文并保留故事核心。"

    def build_rewrite_context(self, progress: Progress | None, context: dict[str, Any]) -> dict[str, Any]:
        """构建重写上下文，将评审意见注入到 context 中。

        Args:
            progress: 进度对象（dataclass），包含 pending_rewrites、rewrite_reason 等
            context: 原始上下文（来自 novel_context 工具）

        Returns:
            注入了重写信息的上下文
        """
        context = dict(context or {})
        chapter = progress.pending_rewrites[0] if progress and progress.pending_rewrites else 0
        if chapter > 0:
            review = self.store.world.load_last_review(chapter)
            if review:
                context["latest_review"] = asdict(review)
                # P2 修复：issue 元素加 None 防御，避免 asdict(None) 抛 TypeError
                context["rewrite_issues"] = [
                    asdict(it) for it in (review.issues or []) if it is not None
                ]
        if progress and progress.rewrite_reason:
            context["rewrite_reason"] = progress.rewrite_reason
        return context

    def execute(self, *, chapter: int, context: dict[str, Any], review_result: dict[str, Any], rewrite_mode: str = "rewrite") -> dict[str, Any]:
        issues = review_result.get("issues") or []
        verdict = review_result.get("final_verdict") or review_result.get("verdict") or "rewrite"
        summary = review_result.get("summary") or ""

        # P2 修复：issue_text 拼接对 None 元素加 isinstance 防御
        issue_lines = []
        for it in issues:
            if not isinstance(it, dict):
                continue
            issue_lines.append(
                f"- [{it.get('severity', 'info')}] {it.get('description', '')} (建议: {it.get('suggestion', '')})"
            )
        issue_text = "\n".join(issue_lines) if issue_lines else "无具体问题列表"

        rewrite_notes = (
            f"评审结论: {verdict}\n"
            f"评审摘要: {summary}\n"
            f"需修正的问题:\n{issue_text}\n"
            f"重写模式: {rewrite_mode}"
        )

        # P0 修复：execute() 补 LLM 生成 + draft_chapter 落盘闭环
        client = self.build_client()
        rewrite_prompt = f"""
请根据以下评审意见重写第{chapter}章正文。重写要求：
1. 保持故事核心设定、人物性格、主线推进
2. 针对每条 issue 给出具体修改
3. 章节长度与原文相当（±20%）
4. 仅输出重写后的正文，不要输出 Markdown/JSON 包装

[章节上下文]
{context}

[重写指令]
{rewrite_notes}
""".strip()
        try:
            rewritten_text = _call_with_retry(
                client,
                self.system_prompt(),
                rewrite_prompt,
                temperature=0.4,
            )
            is_fallback = False
            fallback_reason = ""
        except Exception as exc:
            # P1 修复：LLM 失败时 emit_event WARN，调用方通过 is_fallback 标记感知降级
            self.emit_event(Event(
                time=datetime.now(),
                category="AGENT",
                summary=f"RewriteAgent: ch{chapter} LLM 重写失败，使用原上下文兜底。原因: {type(exc).__name__}: {exc}",
                level="warn",
            ))
            rewritten_text = ""  # 落空，调用方知道是降级
            is_fallback = True
            fallback_reason = f"{type(exc).__name__}: {exc}"

        # 落盘：draft_chapter tool
        if rewritten_text:
            self.emit_event(Event(
                time=datetime.now(),
                category="TOOL",
                summary=f"调用 draft_chapter (ch{chapter}, mode=rewrite)",
                level="info",
            ))
            draft_res = self.runner.call_tool(
                "draft_chapter",
                {"chapter": chapter, "content": rewritten_text, "mode": rewrite_mode},
            )
        else:
            draft_res = {}

        self.emit_event(Event(
            time=datetime.now(),
            category="AGENT",
            summary=f"RewriteAgent: 第{chapter}章重写方案已制定 (mode={rewrite_mode}, verdict={verdict}, is_fallback={is_fallback})",
            level="info",
        ))

        return {
            "chapter": chapter,
            "rewrite_mode": rewrite_mode,
            "rewrite_reason": summary,
            "rewrite_issues": issues,
            "rewrite_notes": rewrite_notes,
            "rewritten_text": rewritten_text,
            "is_fallback": is_fallback,
            "_fallback_reason": fallback_reason,
            "draft_res": draft_res,
        }

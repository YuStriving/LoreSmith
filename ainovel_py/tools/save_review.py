from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ainovel_py.domain.checkpoint import arc_scope, chapter_scope
from ainovel_py.domain.review import ReviewEntry
from ainovel_py.domain.runtime import FlowState
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import parse_review_entry

_EXPECTED_DIMENSIONS = {
    "consistency",
    "character",
    "pacing",
    "continuity",
    "foreshadow",
    "hook",
    "aesthetic",
}

_CRITICAL_DIMENSIONS = {"consistency", "character", "continuity"}


class SaveReviewTool:
    """
    评审结果保存工具
    
    负责保存章节评审结果，并根据评审结论决定后续处理流程：
    - accept: 评审通过，继续正常写作
    - polish: 需要打磨，加入打磨队列
    - rewrite: 需要重写，加入重写队列
    
    支持基于合同履约状态和评分卡的自动升级机制。
    """
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        """返回工具名称"""
        return "save_review"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行评审结果保存
        
        Args:
            args: 参数字典，包含评审信息
        
        Returns:
            评审结果字典，包含最终结论和系统提示
        """
        review = parse_review_entry(args)
        normalization_hints: list[str] = []
        
        # 自动填充受影响章节
        if review.verdict in {"rewrite", "polish"} and not review.affected_chapters and review.chapter > 0:
            review.affected_chapters = [review.chapter]
        
        # 标准化维度 verdict
        normalization_hints.extend(self._normalize_dimensions(review))
        
        # 验证评审条目
        self._validate_review_entry(review)

        # 保存评审结果
        self.store.world.save_review(review)
        self.store.signals.save_last_review(asdict(review))

        # 计算最终结论（支持升级）
        final_verdict = review.verdict
        escalation_reason = ""
        if review.verdict == "accept":
            if review.contract_status == "missed":
                final_verdict = "rewrite"
                escalation_reason = "合同履约状态为 missed，升级为重写"
            elif review.contract_status == "partial":
                final_verdict = "polish"
                escalation_reason = "合同履约状态为 partial，升级为打磨"
            if final_verdict == "accept":
                gate = self._evaluate_scorecard_gate(review)
                if gate:
                    final_verdict = "rewrite" if gate.startswith("rewrite:") else "polish"
                    escalation_reason = gate

        # 生成系统提示并更新进度状态
        hints: list[str] = []
        hints.extend(normalization_hints)
        progress = self.store.progress.load()
        
        if final_verdict in {"rewrite", "polish"}:
            completed = set(progress.completed_chapters) if progress else set()
            affected = [ch for ch in review.affected_chapters if ch in completed]
            dropped = [ch for ch in review.affected_chapters if ch not in completed]
            if dropped:
                hints.append(f"[系统] review_filtered: 未完成章节不会进入重写队列 {dropped}。")
            if not affected and review.chapter > 0 and review.chapter in completed:
                affected = [review.chapter]
            
            flow = FlowState.REWRITING
            verb = "重写"
            if final_verdict == "polish":
                flow = FlowState.POLISHING
                verb = "打磨"
            
            self.store.progress.set_pending_rewrites(affected, review.summary)
            self.store.progress.set_flow(flow)
            
            hint = f"[系统] {verb}_required: 审阅结论为 {final_verdict}，受影响章节 {affected}。"
            if escalation_reason:
                hint += f" （升级原因：{escalation_reason}）"
            hint += f" 请逐章调用 writer 执行{verb}，全部完成后再继续写新章节。"
            hints.append(hint)
        else:
            self.store.progress.set_flow(FlowState.WRITING)
            next_ch = progress.next_chapter() if progress else review.chapter + 1
            hints.append(f"[系统] review_accepted: 审阅通过，继续写第 {next_ch} 章。")

        # 记录检查点
        if review.scope == "arc":
            progress = self.store.progress.load()
            vol = progress.current_volume if progress else 0
            arc = progress.current_arc if progress else 0
            self.store.checkpoints.append(arc_scope(vol, arc), "review")
        else:
            self.store.checkpoints.append(chapter_scope(review.chapter), "review")

        return {
            "saved": True,
            "chapter": review.chapter,
            "scope": review.scope,
            "verdict": review.verdict,
            "final_verdict": final_verdict,
            "escalation": escalation_reason,
            "issues": len(review.issues),
            "system_hints": hints,
        }

    def _validate_review_entry(self, review: ReviewEntry) -> None:
        """
        验证评审条目的有效性
        
        Args:
            review: 评审条目对象
        
        Raises:
            ValueError: 验证失败时抛出
        """
        if review.chapter <= 0:
            raise ValueError("chapter must be > 0")
        if not review.scope.strip():
            raise ValueError("scope is required")
        if not review.summary.strip():
            raise ValueError("summary is required")
        if (review.verdict in {"rewrite", "polish"}) and not review.affected_chapters:
            raise ValueError(f"affected_chapters is required when verdict={review.verdict}")

        for issue in review.issues:
            if not issue.description.strip():
                raise ValueError("issue description is required")
            if not issue.evidence.strip():
                raise ValueError("issue evidence is required")

        self._validate_dimensions(review)

    def _normalize_dimensions(self, review: ReviewEntry) -> list[str]:
        """
        标准化维度 verdict，确保与 score 一致
        
        Args:
            review: 评审条目对象
        
        Returns:
            标准化提示列表
        """
        hints: list[str] = []
        for dim in review.dimensions:
            expected = self._expected_dimension_verdict(dim.score)
            if dim.verdict != expected:
                hints.append(
                    f"[系统] review_normalized: 维度 {dim.dimension} 的 verdict 已从 {dim.verdict} 修正为 {expected}（score={dim.score}）。"
                )
                dim.verdict = expected
        return hints

    def _validate_dimensions(self, review: ReviewEntry) -> None:
        """
        验证维度列表的完整性和正确性
        
        Args:
            review: 评审条目对象
        
        Raises:
            ValueError: 验证失败时抛出
        """
        if len(review.dimensions) != len(_EXPECTED_DIMENSIONS):
            raise ValueError(f"dimensions must contain exactly {len(_EXPECTED_DIMENSIONS)} entries")
        
        seen: set[str] = set()
        for dim in review.dimensions:
            if dim.dimension not in _EXPECTED_DIMENSIONS:
                raise ValueError(f"unknown dimension: {dim.dimension}")
            if dim.dimension in seen:
                raise ValueError(f"duplicate dimension: {dim.dimension}")
            seen.add(dim.dimension)
            
            if dim.score < 0 or dim.score > 100:
                raise ValueError(f"invalid score for {dim.dimension}: {dim.score}")
            
            expected = self._expected_dimension_verdict(dim.score)
            if dim.verdict != expected:
                raise ValueError(
                    f"dimension {dim.dimension} has inconsistent score/verdict: score={dim.score} verdict={dim.verdict}"
                )
            
            if dim.dimension == "aesthetic" and not dim.comment.strip():
                raise ValueError("aesthetic comment is required")

    @staticmethod
    def _expected_dimension_verdict(score: int) -> str:
        """
        根据分数计算期望的 verdict
        
        Args:
            score: 维度分数 (0-100)
        
        Returns:
            verdict: pass/warning/fail
        """
        if score >= 80:
            return "pass"
        if score >= 60:
            return "warning"
        return "fail"

    def _evaluate_scorecard_gate(self, review: ReviewEntry) -> str:
        """
        根据评分卡评估是否需要升级评审结论
        
        Args:
            review: 评审条目对象
        
        Returns:
            升级原因字符串（空表示不需要升级）
        """
        critical_fails: list[str] = []
        polish_issues: list[str] = []
        
        for dim in review.dimensions:
            is_critical = dim.dimension in _CRITICAL_DIMENSIONS
            if is_critical and (dim.verdict == "fail" or dim.score < 60):
                critical_fails.append(f"{dim.dimension}({dim.score})")
            elif dim.verdict == "warning" or (is_critical and dim.score < 80):
                polish_issues.append(f"{dim.dimension}({dim.score})")
        
        if critical_fails:
            return f"rewrite: 关键维度不合格 {critical_fails}"
        if polish_issues:
            return f"polish: 部分维度需打磨 {polish_issues}"
        return ""

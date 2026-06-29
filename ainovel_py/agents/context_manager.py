from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextSnapshot:
    """
    上下文快照
    
    记录上下文管理的状态信息，用于追踪上下文压缩策略的执行情况。
    """
    scope: str = ""              # 作用域
    strategy: str = ""           # 压缩策略
    active_messages: int = 0     # 活跃消息数
    summary_messages: int = 0    # 摘要消息数
    compacted_count: int = 0     # 已压缩数量
    kept_count: int = 0          # 保留数量


@dataclass
class WriterRestorePack:
    """
    写作恢复包
    
    包含用于恢复写作状态的上下文信息，包括最近摘要、风格规则、活跃伏笔和评审提醒。
    """
    recent_summaries: list[str] = field(default_factory=list)  # 最近章节摘要
    style_rules: list[str] = field(default_factory=list)       # 风格规则
    foreshadow: list[str] = field(default_factory=list)        # 活跃伏笔
    review_lessons: list[str] = field(default_factory=list)    # 评审提醒

    def refresh(self, context: dict[str, Any]) -> None:
        """从上下文中刷新恢复包内容"""
        self.recent_summaries = [
            str(item.get("summary", "") or "")
            for item in (context.get("recent_summaries") or [])
            if isinstance(item, dict) and str(item.get("summary", "") or "").strip()
        ][:4]
        style = context.get("style_rules") or {}
        self.style_rules = [str(x) for x in (style.get("prose") or []) if str(x).strip()][:5]
        self.foreshadow = [
            f"{item.get('id', '')}:{item.get('description', '')}"
            for item in (context.get("foreshadow_ledger") or [])
            if isinstance(item, dict)
        ][:6]
        latest_review = context.get("latest_review") or {}
        self.review_lessons = [
            str(issue.get("description", "") or "")
            for issue in (latest_review.get("issues") or [])
            if isinstance(issue, dict) and str(issue.get("description", "") or "").strip()
        ][:4]

    def build_text(self) -> str:
        """构建恢复包的文本表示"""
        parts: list[str] = []
        if self.recent_summaries:
            parts.append("[最近章节摘要]\n" + "\n".join(f"- {x}" for x in self.recent_summaries))
        if self.style_rules:
            parts.append("[风格规则]\n" + "\n".join(f"- {x}" for x in self.style_rules))
        if self.foreshadow:
            parts.append("[活跃伏笔]\n" + "\n".join(f"- {x}" for x in self.foreshadow))
        if self.review_lessons:
            parts.append("[最近评审提醒]\n" + "\n".join(f"- {x}" for x in self.review_lessons))
        return "\n\n".join(parts).strip()


@dataclass
class ContextPack:
    """
    上下文包
    
    包含构建完成的摘要块和恢复块，用于传递给 LLM 进行写作。
    """
    summary_block: str = ""              # 摘要块
    restore_block: str = ""              # 恢复块
    compacted_keys: list[str] = field(default_factory=list)  # 已压缩的键列表


@dataclass
class ContextManager:
    """
    上下文管理器
    
    负责管理和压缩 LLM 输入上下文，实现两层上下文压缩策略：
    1. 结构化记忆压缩：将长篇历史转换为摘要
    2. 提示精炼：优化提示词结构
    
    通过配置 context_window、reserve_tokens 和 keep_recent_tokens 来控制压缩行为。
    """
    context_window: int = 128000                  # 上下文窗口大小
    reserve_tokens: int = 32000                   # 预留 token 数
    keep_recent_tokens: int = 30000               # 保留最近内容的 token 数
    snapshots: list[ContextSnapshot] = field(default_factory=list)  # 快照历史
    restore: WriterRestorePack = field(default_factory=WriterRestorePack)  # 恢复包

    def record(self, snapshot: ContextSnapshot) -> None:
        """记录上下文快照"""
        self.snapshots.append(snapshot)

    def latest(self) -> ContextSnapshot | None:
        """获取最新的上下文快照"""
        if not self.snapshots:
            return None
        return self.snapshots[-1]

    def build_writer_pack(self, context: dict[str, Any]) -> ContextPack:
        """
        构建写作上下文包
        
        从输入上下文中提取关键信息，构建结构化的摘要块和恢复块，
        用于传递给写作 Agent 进行章节创作。
        """
        self.restore.refresh(context)
        summary_lines: list[str] = []
        compacted: list[str] = []

        premise = str(context.get("premise", "") or "").strip()
        if premise:
            summary_lines.append("[故事前提]\n" + premise[:300])
            compacted.append("premise")

        characters = [
            item for item in (context.get("characters") or [])
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        ][:8]
        if characters:
            summary_lines.append(
                "[主要人物]\n" + "\n".join(
                    f"- {item.get('name', '')} / {item.get('role', '')}: {item.get('description', '')}" for item in characters
                )
            )
            compacted.append("characters")

        world_rules = [
            item for item in (context.get("world_rules") or [])
            if isinstance(item, dict) and str(item.get("rule", "") or "").strip()
        ][:8]
        if world_rules:
            summary_lines.append(
                "[世界规则]\n" + "\n".join(
                    f"- {item.get('category', '')}: {item.get('rule', '')} {item.get('boundary', '')}".strip() for item in world_rules
                )
            )
            compacted.append("world_rules")

        outline = context.get("current_chapter_outline") or {}
        if outline:
            summary_lines.append(
                "[当前章节大纲]\n"
                + f"标题：{outline.get('title', '')}\n"
                + f"核心事件：{outline.get('core_event', '')}\n"
                + f"钩子：{outline.get('hook', '')}"
            )
            compacted.append("current_chapter_outline")

        chapter_plan = context.get("chapter_plan") or {}
        if chapter_plan:
            contract = chapter_plan.get("contract") or {}
            summary_lines.append(
                "[章节计划]\n"
                + f"目标：{chapter_plan.get('goal', '')}\n"
                + f"冲突：{chapter_plan.get('conflict', '')}\n"
                + f"必达推进：{', '.join(contract.get('required_beats') or [])}\n"
                + f"禁止项：{', '.join(contract.get('forbidden_moves') or [])}"
            )
            compacted.append("chapter_plan")

        summary_block = "\n\n".join(summary_lines).strip()
        restore_block = self.restore.build_text()
        return ContextPack(summary_block=summary_block, restore_block=restore_block, compacted_keys=compacted)

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChapterContract:
    """
    章节契约
    
    定义章节创作的约束条件和质量要求，包括必须完成的情节点、禁止事项、连续性检查等。
    """
    required_beats: list[str] = field(default_factory=list)   # 必须完成的情节点
    forbidden_moves: list[str] = field(default_factory=list)  # 禁止事项
    continuity_checks: list[str] = field(default_factory=list) # 连续性检查项
    evaluation_focus: list[str] = field(default_factory=list)  # 评审关注点
    emotion_target: str = ""        # 情绪目标
    payoff_points: list[str] = field(default_factory=list)     # 待兑现点
    hook_goal: str = ""             # 钩子目标
    min_words: int = 1200           # 最小字数
    target_words: int = 1800        # 目标字数
    max_words: int = 2600           # 最大字数


@dataclass
class ChapterPlan:
    """
    章节计划
    
    包含章节的完整写作计划，包括目标、冲突、钩子和情绪曲线等。
    """
    chapter: int             # 章节号
    title: str               # 章节标题
    goal: str                # 章节目标
    conflict: str            # 核心冲突
    hook: str                # 章末钩子
    emotion_arc: str = ""    # 情绪曲线
    notes: str = ""          # 备注
    contract: ChapterContract = field(default_factory=ChapterContract)  # 章节契约


@dataclass
class PendingRunCheckpoint:
    """
    待确认检查点
    
    记录需要用户确认后才能继续的检查点状态。
    """
    pause_after_chapter: int  # 暂停前已完成的章节
    next_chapter: int         # 下一个要写的章节
    completed_count: int      # 已完成总数
    status: str = "awaiting_confirmation"  # 状态


@dataclass
class ChapterSummary:
    """
    章节摘要
    
    记录章节的关键信息，用于上下文管理和回顾。
    """
    chapter: int                    # 章节号
    summary: str                    # 摘要内容
    characters: list[str] = field(default_factory=list)  # 涉及人物
    key_events: list[str] = field(default_factory=list)  # 关键事件


@dataclass
class ArcSummary:
    """
    篇章摘要
    
    记录篇章级别的摘要信息。
    """
    volume: int                     # 卷号
    arc: int                        # 篇章号
    title: str                      # 篇章标题
    summary: str                    # 摘要内容
    key_events: list[str] = field(default_factory=list)  # 关键事件


@dataclass
class VolumeSummary:
    """
    卷摘要
    
    记录卷级别的摘要信息。
    """
    volume: int                     # 卷号
    title: str                      # 卷标题
    summary: str                    # 摘要内容
    key_events: list[str] = field(default_factory=list)  # 关键事件


@dataclass
class CharacterVoice:
    """
    人物语言风格
    
    定义特定人物的对话风格规则。
    """
    name: str                       # 人物名称
    rules: list[str] = field(default_factory=list)  # 语言规则


@dataclass
class CharacterSnapshot:
    """
    人物快照
    
    记录特定时间点人物的状态快照，包括状态、能力、动机和关系。
    """
    volume: int     # 卷号
    arc: int        # 篇章号
    name: str       # 人物名称
    status: str     # 当前状态
    power: str = ""       # 能力水平
    motivation: str = ""  # 动机
    relations: str = ""   # 关系状态


@dataclass
class WritingStyleRules:
    """
    写作风格规则
    
    定义特定卷/篇章的写作风格约束。
    """
    volume: int                           # 卷号
    arc: int                              # 篇章号
    prose: list[str] = field(default_factory=list)       # 叙事规则
    dialogue: list[CharacterVoice] = field(default_factory=list)  # 对话规则
    taboos: list[str] = field(default_factory=list)      # 禁忌列表
    updated_at: str = ""                  # 更新时间


@dataclass
class OutlineFeedback:
    """
    大纲反馈
    
    记录大纲执行过程中的偏差和改进建议。
    """
    deviation: str     # 偏差描述
    suggestion: str    # 改进建议


@dataclass
class CommitResult:
    """
    提交结果
    
    章节提交后的返回结果，包含字数、下一步章节、评审要求等信息。
    """
    chapter: int                      # 章节号
    committed: bool                   # 是否提交成功
    word_count: int                   # 字数
    next_chapter: int                 # 下一章节
    review_required: bool = False     # 是否需要评审
    review_reason: str = ""           # 评审原因
    hook_type: str = ""               # 钩子类型
    dominant_strand: str = ""         # 主导叙事线
    system_hints: list[str] = field(default_factory=list)  # 系统提示

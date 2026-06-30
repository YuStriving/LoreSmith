from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    """LangGraph 基础状态字典，定义小说创作工作流的状态结构。

    用于在各节点间传递数据，同时作为子图的状态 schema。

    注意：所有键（特别是带下划线前缀的内部字段）都必须在 schema 中声明，
    否则 LangGraph 1.x 在节点间传递 state 时会过滤掉未声明的字段，
    导致循环节点之间的内部状态丢失。
    """
    seed_text: str
    resume_mode: bool
    current_chapter: int
    progress_snapshot: dict[str, Any]
    context: dict[str, Any]
    latest_plan: dict[str, Any]
    latest_draft: str
    latest_word_count: int
    latest_summary: str
    latest_metadata: dict[str, Any]
    latest_commit_result: dict[str, Any]
    latest_review_result: dict[str, Any]
    latest_review_payload: dict[str, Any] | None
    latest_final_verdict: str
    pending_review_for: int | None
    rewrite_mode: str
    pending_actions: list[str]
    pending_action: str
    plan_feedback: str
    plan_decision: str
    stop_requested: bool
    error: str
    out_lines: list[str]
    # 内部状态字段（节点间传递的临时数据，跨节点循环必须保留）
    _plan_validation_ok: bool
    _plan_review_score: int
    _plan_review_issues: list[str]
    _plan_review_attempts: int
    _plan_review_approved: bool
    _plan_normalized: bool
    latest_plan_cache_hit: bool


class OrchestratorState(GraphState, total=False):
    """主 Agent 编排层的状态字典，扩展 GraphState 增加调度相关字段。

    在 GraphState 基础上新增：
    - current_tag: 当前正在执行的 TaskTag
    - last_completed_tag: 上一个完成的 TaskTag
    - dispatch_reason: 分派理由（供日志/调试）
    """
    current_tag: str
    last_completed_tag: str
    dispatch_reason: str
    supervisor_decision: dict[str, Any] | None

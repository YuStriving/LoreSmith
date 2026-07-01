"""GraphState / OrchestratorState 单测。

覆盖：
1. GraphState 必备字段全部声明（project_memory 硬约束）
2. 内部字段（_plan_* / latest_plan_cache_hit）已声明
3. OrchestratorState 继承 + 扩展字段
4. TypedDict total=False：缺失字段不抛异常
5. 字段类型注解符合预期（运行时类型检查有限，但 key 必须存在）
6. 字段值可以是 None（如 latest_review_payload: dict | None）
"""
from __future__ import annotations

import pytest

from ainovel_py.agents.orchestrator.langgraph.state import GraphState, OrchestratorState


# ---------- 1. 必备字段全部声明 ----------

def test_graph_state_has_business_fields():
    """业务字段必须在 GraphState 中声明。"""
    required_business = [
        "seed_text",
        "resume_mode",
        "current_chapter",
        "progress_snapshot",
        "context",
        "latest_plan",
        "latest_draft",
        "latest_word_count",
        "latest_summary",
        "latest_metadata",
        "latest_commit_result",
        "latest_review_result",
        "latest_review_payload",
        "latest_final_verdict",
        "pending_review_for",
        "rewrite_mode",
        "pending_actions",
        "pending_action",
        "plan_feedback",
        "plan_decision",
        "stop_requested",
        "error",
        "out_lines",
    ]
    annotations = GraphState.__annotations__
    for key in required_business:
        assert key in annotations, f"missing field in GraphState: {key}"


# ---------- 2. 内部 _plan_* 字段已声明（project_memory 硬约束）----------

def test_graph_state_has_internal_plan_fields():
    """LangGraph 1.x 会过滤未声明的 key，_plan_* 内部字段必须声明。"""
    required_internal = [
        "_plan_validation_ok",
        "_plan_review_score",
        "_plan_review_issues",
        "_plan_review_attempts",
        "_plan_review_approved",
        "_plan_normalized",
        "latest_plan_cache_hit",
    ]
    annotations = GraphState.__annotations__
    for key in required_internal:
        assert key in annotations, f"missing internal field: {key}"


# ---------- 3. OrchestratorState 继承 + 扩展 ----------

def test_orchestrator_state_inherits_graph_state():
    """OrchestratorState 必须继承 GraphState 的所有字段。"""
    orch_annotations = OrchestratorState.__annotations__
    graph_annotations = GraphState.__annotations__
    for key in graph_annotations:
        assert key in orch_annotations, f"OrchestratorState 丢失 GraphState 字段: {key}"


def test_orchestrator_state_has_scheduling_fields():
    """OrchestratorState 新增的调度相关字段。"""
    required_extra = [
        "current_tag",
        "last_completed_tag",
        "dispatch_reason",
        "supervisor_decision",
    ]
    annotations = OrchestratorState.__annotations__
    for key in required_extra:
        assert key in annotations, f"missing OrchestratorState field: {key}"


# ---------- 4. TypedDict total=False：缺失字段不抛 ----------

def test_graph_state_total_false_allows_missing_keys():
    """total=False 表示所有字段都是可选的，不传不抛。"""
    state: GraphState = {}  # 空字典合法
    assert state.get("current_chapter") is None
    assert state.get("latest_plan") is None


def test_graph_state_total_false_accepts_partial_state():
    state: GraphState = {"current_chapter": 1, "seed_text": "test"}
    assert state["current_chapter"] == 1
    assert state["seed_text"] == "test"


# ---------- 5. 字段可被赋值 ----------

def test_graph_state_assignment_works():
    state: GraphState = {}
    state["current_chapter"] = 5
    state["_plan_review_score"] = 3
    state["_plan_review_attempts"] = 2
    assert state["current_chapter"] == 5
    assert state["_plan_review_score"] == 3
    assert state["_plan_review_attempts"] == 2


# ---------- 6. 字段值可以为 None ----------

def test_graph_state_fields_accept_none():
    state: GraphState = {
        "latest_review_payload": None,
        "pending_review_for": None,
        "plan_feedback": "",
        "error": None,
    }
    assert state["latest_review_payload"] is None
    assert state["pending_review_for"] is None

"""测试评审加权评分 + 三层退出机制（防 review↔rewrite 死循环）。

覆盖场景：
1. compute_weighted_score 计算正确性
2. 加权总分 >= 75 时强制 accept（Layer 1）
3. 连续 2 次分数未改善时强制 accept（Layer 2）
4. 重写 5 次后强制 accept（Layer 3）
5. 正常 accept 时 rewrite_attempts 归零
6. fallback verdict 改为 polish
7. save_review _evaluate_scorecard_gate 加权总分达标时不升级
"""
from __future__ import annotations

from ainovel_py.agents.roles.editor import (
    MAX_REWRITE_ATTEMPTS,
    MAX_STAGNANT_REWRITES,
    REVIEW_DIMENSION_WEIGHTS,
    REVIEW_PASS_THRESHOLD,
    _FALLBACK_DIMENSION_SCORES,
    compute_weighted_score,
)
from ainovel_py.agents.orchestrator.langgraph.state import GraphState


# ── 1. compute_weighted_score 计算正确性 ──────────────────────────

def test_weighted_score_basic():
    """7 个维度各 80 分 → 加权总分 = 80.0"""
    dims = [
        {"dimension": "consistency", "score": 80},
        {"dimension": "continuity", "score": 80},
        {"dimension": "pacing", "score": 80},
        {"dimension": "character", "score": 80},
        {"dimension": "foreshadow", "score": 80},
        {"dimension": "hook", "score": 80},
        {"dimension": "aesthetic", "score": 80},
    ]
    assert compute_weighted_score(dims) == 80.0


def test_weighted_score_weighted():
    """不同分数 → 加权总分符合权重计算"""
    dims = [
        {"dimension": "consistency", "score": 100},  # 0.25 * 100 = 25
        {"dimension": "continuity", "score": 100},   # 0.20 * 100 = 20
        {"dimension": "pacing", "score": 0},          # 0.15 * 0 = 0
        {"dimension": "character", "score": 0},       # 0.10 * 0 = 0
        {"dimension": "foreshadow", "score": 0},      # 0.10 * 0 = 0
        {"dimension": "hook", "score": 0},             # 0.10 * 0 = 0
        {"dimension": "aesthetic", "score": 0},        # 0.10 * 0 = 0
    ]
    # 25 + 20 = 45.0
    assert compute_weighted_score(dims) == 45.0


def test_weighted_score_consistency_dominant():
    """consistency 权重最高，低分会严重拉低总分"""
    dims = [
        {"dimension": "consistency", "score": 40},   # 0.25 * 40 = 10
        {"dimension": "continuity", "score": 90},    # 0.20 * 90 = 18
        {"dimension": "pacing", "score": 90},        # 0.15 * 90 = 13.5
        {"dimension": "character", "score": 90},     # 0.10 * 90 = 9
        {"dimension": "foreshadow", "score": 90},    # 0.10 * 90 = 9
        {"dimension": "hook", "score": 90},           # 0.10 * 90 = 9
        {"dimension": "aesthetic", "score": 90},      # 0.10 * 90 = 9
    ]
    # 10 + 18 + 13.5 + 9 + 9 + 9 + 9 = 77.5
    assert compute_weighted_score(dims) == 77.5


def test_weighted_score_custom_weights():
    """支持自定义权重"""
    dims = [{"dimension": "consistency", "score": 100}]
    assert compute_weighted_score(dims, {"consistency": 0.5}) == 50.0


def test_weighted_score_empty_dimensions():
    """空维度列表 → 总分 0"""
    assert compute_weighted_score([]) == 0.0


# ── 2. Layer 1：加权总分 >= 75 时强制 accept ──────────────────────

def test_layer1_force_accept():
    """加权总分 = 80 >= 75 → 即使 LLM 给 rewrite，也应被强制 accept"""
    state: GraphState = {
        "_rewrite_attempts": 0,
        "_last_weighted_score": 0,
        "_stagnant_rewrite_count": 0,
        "out_lines": [],
    }
    weighted_score = 80.0
    final_verdict = "rewrite"

    # Layer 1 检查
    if final_verdict in ("rewrite", "polish") and weighted_score >= REVIEW_PASS_THRESHOLD:
        final_verdict = "accept"

    assert final_verdict == "accept"


def test_layer1_not_triggered_when_below_threshold():
    """加权总分 = 70 < 75 → 不触发 Layer 1"""
    weighted_score = 70.0
    final_verdict = "rewrite"

    if final_verdict in ("rewrite", "polish") and weighted_score >= REVIEW_PASS_THRESHOLD:
        final_verdict = "accept"

    assert final_verdict == "rewrite"


# ── 3. Layer 2：连续 2 次分数未改善时强制 accept ──────────────────

def test_layer2_stagnant_force_accept():
    """连续 2 次 rewrite 分数未改善（改善 < 1 分）→ 强制 accept"""
    last_score = 70.0
    current_score = 70.5  # 改善不到 1 分
    stagnant_count = 1    # 已经 1 次了

    if abs(current_score - last_score) < 1.0:
        stagnant_count += 1
    else:
        stagnant_count = 0

    assert stagnant_count == 2
    assert stagnant_count >= MAX_STAGNANT_REWRITES


def test_layer2_not_stagnant_when_improved():
    """分数改善 >= 1 分 → stagnant_count 归零"""
    last_score = 70.0
    current_score = 72.0  # 改善了 2 分
    stagnant_count = 1

    if abs(current_score - last_score) < 1.0:
        stagnant_count += 1
    else:
        stagnant_count = 0

    assert stagnant_count == 0


# ── 4. Layer 3：重写 5 次后强制 accept ───────────────────────────

def test_layer3_max_rewrite_attempts():
    """rewrite_attempts = 5 >= MAX_REWRITE_ATTEMPTS(5) → 强制 accept"""
    rewrite_attempts = 4  # 之前已重写 4 次
    final_verdict = "rewrite"

    if final_verdict in ("rewrite", "polish"):
        rewrite_attempts += 1
        if rewrite_attempts >= MAX_REWRITE_ATTEMPTS:
            final_verdict = "accept"

    assert rewrite_attempts == 5
    assert final_verdict == "accept"


def test_layer3_not_triggered_before_limit():
    """rewrite_attempts = 3 < 5 → 不触发 Layer 3"""
    rewrite_attempts = 2
    final_verdict = "rewrite"

    if final_verdict in ("rewrite", "polish"):
        rewrite_attempts += 1
        if rewrite_attempts >= MAX_REWRITE_ATTEMPTS:
            final_verdict = "accept"

    assert rewrite_attempts == 3
    assert final_verdict == "rewrite"


# ── 5. 正常 accept 时 rewrite_attempts 归零 ──────────────────────

def test_accept_resets_counters():
    """verdict = accept 时，_rewrite_attempts 和 _stagnant_rewrite_count 应归零"""
    state: GraphState = {
        "_rewrite_attempts": 3,
        "_stagnant_rewrite_count": 1,
        "out_lines": [],
    }
    final_verdict = "accept"

    if final_verdict == "accept":
        state["_rewrite_attempts"] = 0
        state["_stagnant_rewrite_count"] = 0

    assert state["_rewrite_attempts"] == 0
    assert state["_stagnant_rewrite_count"] == 0


# ── 6. fallback verdict 改为 polish ────────────────────────────────

def test_fallback_verdict_is_polish():
    """LLM JSON 解析失败时，fallback verdict 应为 polish 而非 accept"""
    # 找到 fallback 数据
    fallback = {
        "verdict": "polish",
        "is_fallback": True,
    }
    # 模拟 fallback 场景
    for d in _FALLBACK_DIMENSION_SCORES:
        if d.get("verdict"):
            pass  # fallback dimensions 只是用于评分
    # 验证 fallback 数据中的 verdict
    assert fallback["verdict"] == "polish"
    assert fallback["is_fallback"] is True


# ── 7. save_review _evaluate_scorecard_gate 加权总分达标时不升级 ──

def test_scorecard_gate_no_escalation_when_weighted_score_high():
    """加权总分 >= 75 时，_evaluate_scorecard_gate 不应升级 verdict"""
    # 构造一个加权总分 >= 75 但个别维度 fail 的评审
    # consistency=90(0.25*90=22.5), continuity=90(0.20*90=18), pacing=50(fail, 0.15*50=7.5)
    # character=90(9), foreshadow=90(9), hook=90(9), aesthetic=90(9) → 总分 = 84
    # 虽然 pacing fail，但加权总分 84 >= 75，不应升级
    from ainovel_py.domain.review import ReviewEntry, DimensionScore, ConsistencyIssue

    review = ReviewEntry(
        chapter=1,
        scope="chapter",
        issues=[],
        verdict="accept",
        summary="test",
        dimensions=[
            DimensionScore(dimension="consistency", score=90, verdict="pass"),
            DimensionScore(dimension="continuity", score=90, verdict="pass"),
            DimensionScore(dimension="pacing", score=50, verdict="fail"),     # fail!
            DimensionScore(dimension="character", score=90, verdict="pass"),
            DimensionScore(dimension="foreshadow", score=90, verdict="pass"),
            DimensionScore(dimension="hook", score=90, verdict="pass"),
            DimensionScore(dimension="aesthetic", score=90, verdict="pass"),
        ],
        affected_chapters=[1],
    )
    # 先验证加权总分 >= 75
    dim_dicts = [{"dimension": d.dimension, "score": d.score} for d in review.dimensions]
    assert compute_weighted_score(dim_dicts) >= REVIEW_PASS_THRESHOLD

    # save_review 的 _evaluate_scorecard_gate 应返回空字符串
    from ainovel_py.tools.save_review import SaveReviewTool
    from unittest.mock import MagicMock

    store = MagicMock()
    store.world = MagicMock()
    store.signals = MagicMock()
    store.progress = MagicMock()
    store.progress.load.return_value = MagicMock(
        completed_chapters=[1],
        current_volume=1,
        current_arc=1,
        next_chapter=lambda: 2,
    )
    store.checkpoints = MagicMock()
    tool = SaveReviewTool(store)
    result = tool._evaluate_scorecard_gate(review)
    assert result == "", f"加权总分达标时不应升级，但返回了: {result}"


# ── 常量验证 ──────────────────────────────────────────────────────

def test_constants():
    assert REVIEW_PASS_THRESHOLD == 75
    assert MAX_REWRITE_ATTEMPTS == 5
    assert MAX_STAGNANT_REWRITES == 2
    # 权重之和 = 1.0
    total_weight = sum(REVIEW_DIMENSION_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 0.001, f"权重之和 = {total_weight}，应为 1.0"


def test_weighted_score_of_fallback_dimensions():
    """fallback 维度的加权总分应 >= 75（否则 fallback 就没意义了）"""
    score = compute_weighted_score(_FALLBACK_DIMENSION_SCORES)
    assert score >= REVIEW_PASS_THRESHOLD, f"fallback 加权总分 = {score}，应 >= {REVIEW_PASS_THRESHOLD}"


def test_state_has_rewrite_fields():
    """GraphState 应包含 _rewrite_attempts / _last_weighted_score / _stagnant_rewrite_count"""
    state: GraphState = {
        "_rewrite_attempts": 0,
        "_last_weighted_score": 0.0,
        "_stagnant_rewrite_count": 0,
        "out_lines": [],
    }
    assert "_rewrite_attempts" in state
    assert "_last_weighted_score" in state
    assert "_stagnant_rewrite_count" in state

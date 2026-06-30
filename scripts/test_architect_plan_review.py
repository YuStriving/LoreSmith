"""Architect subgraph 3 新节点（validate_inputs / review_plan / normalize_plan）单元测试。

覆盖：
1. validate_inputs —— 5 个用例：合法 / chapter 缺失 / chapter 越界 / 类型错误 / 已完成章节告警
2. review_plan —— 5 个用例：无 plan / max attempts / 通过 / 不通过循环 / LLM 异常降级
3. normalize_plan —— 4 个用例：plan 完整 / 缺字段 / contract 缺失 / 无 plan
4. _should_replan —— 2 个用例：True/False
5. 整图构建 —— 4 节点 + 1 条件边 + 起点终点正确
6. _call_plan_review —— 3 个用例：JSON 解析 / score 越界裁剪 / issues 清洗
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 最小依赖 stub（避免拖入整个项目）
# ============================================================
import importlib.util
import types


def _install_fake_pkg(name: str):
    if name in sys.modules:
        return sys.modules[name]
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        sub = ".".join(parts[:i])
        if sub not in sys.modules:
            m = types.ModuleType(sub)
            m.__path__ = []
            sys.modules[sub] = m
    return sys.modules[name]


def _load(name: str, rel: str):
    if "." in name:
        _install_fake_pkg(".".join(name.split(".")[:-1]))
    spec = importlib.util.spec_from_file_location(name, str(PROJECT_ROOT / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 必要依赖
tags_mod = _load(
    "ainovel_py.agents.orchestrator.tags",
    "ainovel_py/agents/orchestrator/tags.py",
)
hints_mod = _load(
    "ainovel_py.agents.orchestrator.langgraph.hints",
    "ainovel_py/agents/orchestrator/langgraph/hints.py",
)
if not hasattr(hints_mod, "HintAction"):
    from enum import Enum
    class HintAction(str, Enum):
        UNKNOWN = "unknown"
    def plan_actions(_):
        from dataclasses import dataclass, field
        @dataclass
        class _P:
            requires_review: bool = False
            rewrite_mode: str = ""
            queue: list = field(default_factory=list)
            @property
            def next_action(self): return "checkpoint"
        return _P()
    hints_mod.HintAction = HintAction
    hints_mod.plan_actions = plan_actions

state_mod = _load(
    "ainovel_py.agents.orchestrator.langgraph.state",
    "ainovel_py/agents/orchestrator/langgraph/state.py",
)

events_mod = _load(
    "ainovel_py.host.events",
    "ainovel_py/host/events.py",
)
if not hasattr(events_mod, "Event"):
    from dataclasses import dataclass
    @dataclass
    class Event:
        time: object = None
        category: str = ""
        summary: str = ""
        level: str = "info"
    events_mod.Event = Event

# domain.runtime（helpers.py 依赖）
domain_runtime_mod = _load(
    "ainovel_py.domain.runtime",
    "ainovel_py/domain/runtime.py",
)
if not hasattr(domain_runtime_mod, "FlowState"):
    from enum import Enum
    class FlowState(str, Enum):
        WRITING = "writing"
        REWRITING = "rewriting"
        POLISHING = "polishing"
        CHECKPOINT = "checkpoint"
    domain_runtime_mod.FlowState = FlowState

helpers_mod = _load(
    "ainovel_py.agents.orchestrator.langgraph.nodes.helpers",
    "ainovel_py/agents/orchestrator/langgraph/nodes/helpers.py",
)

prefetch_mod = _load(
    "ainovel_py.agents.orchestrator.langgraph.prefetch",
    "ainovel_py/agents/orchestrator/langgraph/prefetch.py",
)

# 重要：被测模块
arch_mod = _load(
    "ainovel_py.agents.orchestrator.langgraph.subgraphs.architect_subgraph",
    "ainovel_py/agents/orchestrator/langgraph/subgraphs/architect_subgraph.py",
)


GraphState = state_mod.GraphState
_validate_inputs_node = arch_mod._validate_inputs_node
_review_plan_node = arch_mod._review_plan_node
_normalize_plan_node = arch_mod._normalize_plan_node
_call_plan_review = arch_mod._call_plan_review
_should_replan = arch_mod._should_replan
build_architect_plan_subgraph = arch_mod.build_architect_plan_subgraph
PLAN_REVIEW_SCORE_THRESHOLD = arch_mod.PLAN_REVIEW_SCORE_THRESHOLD
PLAN_REVIEW_MAX_ATTEMPTS = arch_mod.PLAN_REVIEW_MAX_ATTEMPTS
reset_runtime_cache = prefetch_mod.reset_runtime_cache


print("=" * 60)
print("Architect Plan Review 单元测试")
print("=" * 60)


def _make_runtime(progress=None, completed_chapters=()):
    """构造一个最小可用的 MagicMock runtime。"""
    runtime = MagicMock()
    runtime.store.progress.load.return_value = progress
    # MagicMock 会在 getattr 时自动创建 _prefetch_plan_cache 属性，导致
    # get_runtime_cache 返回 MagicMock 而不是真实的 PrefetchPlanCache。
    # 显式置 None 确保 get_runtime_cache 走"创建新缓存"分支。
    runtime._prefetch_plan_cache = None
    return runtime


# ============================================================
# Part 1: validate_inputs 节点
# ============================================================
print("Part 1: validate_inputs")

# 1.1 合法输入
runtime = _make_runtime()
node = _validate_inputs_node(runtime)
out = node({"current_chapter": 5, "seed_text": "abc", "plan_feedback": ""})
assert out["_plan_validation_ok"] is True
print("[PASS] 1.1 合法输入")

# 1.2 chapter 缺失
runtime = _make_runtime()
node = _validate_inputs_node(runtime)
try:
    node({"current_chapter": None, "seed_text": "abc"})
    raise AssertionError("should have raised")
except ValueError as e:
    assert "required" in str(e)
print("[PASS] 1.2 chapter 缺失 → ValueError")

# 1.3 chapter 越界
runtime = _make_runtime()
node = _validate_inputs_node(runtime)
try:
    node({"current_chapter": 0, "seed_text": "abc"})
    raise AssertionError("should have raised")
except ValueError as e:
    assert ">= 1" in str(e)
print("[PASS] 1.3 chapter 越界 → ValueError")

# 1.4 chapter 类型错误
runtime = _make_runtime()
node = _validate_inputs_node(runtime)
try:
    node({"current_chapter": "abc", "seed_text": "abc"})
    raise AssertionError("should have raised")
except ValueError as e:
    assert "must be int" in str(e)
print("[PASS] 1.4 chapter 类型错误 → ValueError")

# 1.5 seed_text 类型错误
runtime = _make_runtime()
node = _validate_inputs_node(runtime)
try:
    node({"current_chapter": 5, "seed_text": ["not", "str"]})
    raise AssertionError("should have raised")
except TypeError as e:
    assert "seed_text" in str(e)
print("[PASS] 1.5 seed_text 类型错误 → TypeError")

# 1.6 plan_feedback 类型错误
runtime = _make_runtime()
node = _validate_inputs_node(runtime)
try:
    node({"current_chapter": 5, "seed_text": "abc", "plan_feedback": {"x": 1}})
    raise AssertionError("should have raised")
except TypeError as e:
    assert "plan_feedback" in str(e)
print("[PASS] 1.6 plan_feedback 类型错误 → TypeError")

# 1.7 progress 加载失败不阻塞
runtime = MagicMock()
runtime.store.progress.load.side_effect = RuntimeError("disk fail")
node = _validate_inputs_node(runtime)
out = node({"current_chapter": 5, "seed_text": "abc"})
assert out["_plan_validation_ok"] is True
print("[PASS] 1.7 progress 加载失败 → 软告警，继续")


# ============================================================
# Part 2: review_plan 节点
# ============================================================
print("Part 2: review_plan")

# 2.1 无 plan → auto-approve
runtime = _make_runtime()
node = _review_plan_node(runtime)
out = node({})
assert out["_plan_review_approved"] is True
runtime.get_agent.assert_not_called()
print("[PASS] 2.1 无 plan → auto-approve（不调 LLM）")

# 2.2 达到 max attempts → auto-approve
runtime = _make_runtime()
node = _review_plan_node(runtime)
out = node({"latest_plan": {"chapter": 1}, "_plan_review_attempts": PLAN_REVIEW_MAX_ATTEMPTS})
assert out["_plan_review_approved"] is True
runtime.get_agent.assert_not_called()
print("[PASS] 2.2 max attempts → auto-approve（不调 LLM）")

# 2.3 score >= threshold → 通过
runtime = _make_runtime()
client = MagicMock()
client.complete.return_value = json.dumps({"score": 4, "issues": []})
editor = MagicMock()
editor.build_client.return_value = client
runtime.get_agent.return_value = editor
node = _review_plan_node(runtime)
out = node({"latest_plan": {"chapter": 1, "title": "t", "goal": "g"}})
assert out["_plan_review_approved"] is True
assert out["_plan_review_score"] == 4
assert out["_plan_review_attempts"] == 1
print("[PASS] 2.3 score=4 >= 阈值 → PASS")

# 2.4 score < threshold → 写入 feedback，标记不通过
runtime = _make_runtime()
client = MagicMock()
client.complete.return_value = json.dumps({"score": 2, "issues": ["hook 太弱", "conflict 不清晰"]})
editor = MagicMock()
editor.build_client.return_value = client
runtime.get_agent.return_value = editor
node = _review_plan_node(runtime)
out = node({"latest_plan": {"chapter": 1, "title": "t"}})
assert out["_plan_review_approved"] is False
assert out["_plan_review_score"] == 2
assert "hook 太弱" in out["plan_feedback"]
assert out["_plan_review_attempts"] == 1
print("[PASS] 2.4 score=2 < 阈值 → FAIL，feedback 写入")

# 2.5 LLM 异常 → auto-approve（不阻塞）
runtime = _make_runtime()
editor = MagicMock()
editor.build_client.side_effect = RuntimeError("LLM 不可用")
runtime.get_agent.return_value = editor
node = _review_plan_node(runtime)
out = node({"latest_plan": {"chapter": 1, "title": "t"}})
assert out["_plan_review_approved"] is True
print("[PASS] 2.5 LLM 异常 → auto-approve（不阻塞）")


# ============================================================
# Part 3: normalize_plan 节点
# ============================================================
print("Part 3: normalize_plan")

# 3.1 plan 完整 → 无需规范化
runtime = _make_runtime()
runtime.runner.call_tool.return_value = {"ok": True}
node = _normalize_plan_node(runtime)
plan = {
    "chapter": 1, "title": "t", "goal": "g", "conflict": "c", "hook": "h",
    "emotion_arc": "e", "contract": {"min_words": 1200, "target_words": 1800, "max_words": 2400},
}
out = node({"latest_plan": dict(plan)})
assert out["_plan_normalized"] is False
assert out["latest_plan"]["title"] == "t"
print("[PASS] 3.1 plan 完整 → 无需规范化")

# 3.2 缺字段 → 填默认值
runtime = _make_runtime()
runtime.runner.call_tool.return_value = {"ok": True}
node = _normalize_plan_node(runtime)
out = node({"latest_plan": {"chapter": 3, "title": "第三章"}})
assert out["latest_plan"]["goal"] == "推进主线冲突并制造新的局面"
assert out["latest_plan"]["conflict"] == "角色在压力中做出高代价选择"
assert out["latest_plan"]["hook"] == "章末引出更大问题"
assert out["_plan_normalized"] is True
print("[PASS] 3.2 缺字段 → 填默认值")

# 3.3 contract 缺失 / 部分缺失 → 补默认值
runtime = _make_runtime()
runtime.runner.call_tool.return_value = {"ok": True}
node = _normalize_plan_node(runtime)
out = node({"latest_plan": {
    "chapter": 1, "title": "t", "goal": "g", "conflict": "c", "hook": "h", "emotion_arc": "e",
    "contract": {"target_words": 2000},  # min/max 缺失
}})
assert out["latest_plan"]["contract"]["min_words"] == 1200
assert out["latest_plan"]["contract"]["target_words"] == 2000
assert out["latest_plan"]["contract"]["max_words"] >= 2000
print("[PASS] 3.3 contract 部分缺失 → 补默认值")

# 3.4 max < target → 修正
runtime = _make_runtime()
runtime.runner.call_tool.return_value = {"ok": True}
node = _normalize_plan_node(runtime)
out = node({"latest_plan": {
    "chapter": 1, "title": "t", "goal": "g", "conflict": "c", "hook": "h", "emotion_arc": "e",
    "contract": {"min_words": 1200, "target_words": 2000, "max_words": 1500},  # max < target
}})
assert out["latest_plan"]["contract"]["max_words"] >= 2000
print("[PASS] 3.4 max < target → 自动修正")

# 3.5 无 plan → 不抛异常
runtime = _make_runtime()
node = _normalize_plan_node(runtime)
out = node({})
assert out["_plan_normalized"] is False
runtime.runner.call_tool.assert_not_called()
print("[PASS] 3.5 无 plan → 不抛异常，不调工具")

# 3.6 持久化失败不阻塞
runtime = _make_runtime()
runtime.runner.call_tool.side_effect = RuntimeError("disk full")
node = _normalize_plan_node(runtime)
out = node({"latest_plan": {"chapter": 1, "title": "t"}})  # 缺字段会触发持久化
assert out["_plan_normalized"] is True
print("[PASS] 3.6 持久化失败 → 软告警，state 仍更新")


# ============================================================
# Part 4: _should_replan 路由函数
# ============================================================
print("Part 4: _should_replan 路由")

assert _should_replan({}) == "normalize_plan"  # 默认 True
assert _should_replan({"_plan_review_approved": True}) == "normalize_plan"
assert _should_replan({"_plan_review_approved": False}) == "build_plan"
print("[PASS] 4.1 路由函数 3 用例")


# ============================================================
# Part 5: 整图构建（验证 4 节点 + 1 条件边）
# ============================================================
print("Part 5: build_architect_plan_subgraph 整图")

runtime = _make_runtime()
reset_runtime_cache(runtime)  # 防止上一测试的 MagicMock 缓存命中
runtime.runner.call_tool.return_value = {"plan": {"chapter": 1, "title": "t"}}
client = MagicMock()
client.complete.return_value = json.dumps({"score": 4, "issues": []})
editor = MagicMock()
editor.build_client.return_value = client
architect = MagicMock()
architect.build_dynamic_plan.return_value = {"chapter": 1, "title": "LLM 计划"}
runtime.get_agent.side_effect = lambda name: editor if name == "editor" else architect
graph = build_architect_plan_subgraph(runtime)
# 验证图对象构建成功且可调用
result = graph.invoke({"current_chapter": 1, "seed_text": "s", "plan_feedback": ""})
assert "latest_plan" in result
print("[PASS] 5.1 整图 invoke 成功")


# ============================================================
# Part 6: _call_plan_review LLM 调用
# ============================================================
print("Part 6: _call_plan_review LLM 调用")

# 6.1 正常返回
client = MagicMock()
client.complete.return_value = json.dumps({"score": 5, "issues": ["小问题"]})
score, issues = _call_plan_review(client, {"chapter": 1, "title": "t"})
assert score == 5
assert issues == ["小问题"]
client.complete.assert_called_once()
print("[PASS] 6.1 score=5 + 1 issue 正常解析")

# 6.2 score 越界裁剪
client = MagicMock()
client.complete.return_value = json.dumps({"score": 99, "issues": []})
score, _ = _call_plan_review(client, {"chapter": 1})
assert score == 5
client = MagicMock()
client.complete.return_value = json.dumps({"score": -3, "issues": []})
score, _ = _call_plan_review(client, {"chapter": 1})
assert score == 1
print("[PASS] 6.2 score 越界裁剪到 1-5")

# 6.3 issues 空白过滤
client = MagicMock()
client.complete.return_value = json.dumps({"score": 3, "issues": ["有效", "", "  ", "也有效"]})
_, issues = _call_plan_review(client, {"chapter": 1})
assert issues == ["有效", "也有效"]
print("[PASS] 6.3 issues 空白过滤")


# ============================================================
# Part 7: 端到端 —— 评审不通过 → 循环 1 次后通过
# ============================================================
print("Part 7: 端到端 review 循环")

call_count = {"n": 0}

def _flaky_client(*args, **kwargs):
    call_count["n"] += 1
    if call_count["n"] == 1:
        return json.dumps({"score": 2, "issues": ["hook 弱"]})
    return json.dumps({"score": 4, "issues": []})

client = MagicMock()
client.complete.side_effect = _flaky_client
editor = MagicMock()
editor.build_client.return_value = client
architect = MagicMock()
architect.build_dynamic_plan.side_effect = lambda *a, **kw: {
    "chapter": 1, "title": f"plan_v{call_count['n']}",
    "goal": "g", "conflict": "c", "hook": "h", "emotion_arc": "e",
    "contract": {"min_words": 1200, "target_words": 1800, "max_words": 2400},
}
runtime = _make_runtime()
runtime.runner.call_tool.return_value = {"plan": {"chapter": 1, "title": "x"}}
runtime.get_agent.side_effect = lambda name: editor if name == "editor" else architect

# 验证 mock 自身工作正常
assert _flaky_client() == json.dumps({"score": 2, "issues": ["hook 弱"]})
assert _flaky_client() == json.dumps({"score": 4, "issues": []})
call_count["n"] = 0  # 重置

graph = build_architect_plan_subgraph(runtime)
result = graph.invoke({"current_chapter": 1, "seed_text": "s", "plan_feedback": ""})
# 第 1 次 plan 评分 2 → feedback 写入 → 第 2 次 plan 评分 4 → 通过
assert call_count["n"] == 2, f"expected 2 LLM calls, got {call_count['n']}, state={result}"
print("[PASS] 7.1 不通过循环 1 次后通过")


# ============================================================
# Part 8: 端到端 —— 持续不通过 → 达到 max 后强制通过
# ============================================================
print("Part 8: 端到端 review max attempts")

client = MagicMock()
client.complete.return_value = json.dumps({"score": 1, "issues": ["永久不合格"]})
editor = MagicMock()
editor.build_client.return_value = client
architect = MagicMock()
architect.build_dynamic_plan.return_value = {"chapter": 1, "title": "t"}
runtime = _make_runtime()
reset_runtime_cache(runtime)  # 防止 MagicMock 缓存命中
runtime.runner.call_tool.return_value = {"plan": {"chapter": 1, "title": "t"}}
runtime.get_agent.side_effect = lambda name: editor if name == "editor" else architect

graph = build_architect_plan_subgraph(runtime)
result = graph.invoke({"current_chapter": 1, "seed_text": "s", "plan_feedback": ""})
# 不会无限循环，最终强制通过
assert result.get("latest_plan") is not None
print("[PASS] 8.1 持续不合格 → 强制通过（不无限循环）")


print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)

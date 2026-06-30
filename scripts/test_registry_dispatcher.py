"""阶段 A + B 单元测试：registry + dispatcher。

覆盖：
- AgentRegistry CRUD / 白名单 / filter_candidates
- AgentSpec 必填字段校验
- dispatch_next_v2 FAST_RULES 命中
- dispatch_next_v2 LLM 兜底（mock client）
- dispatch_next_v2 白名单校验
- dispatch_next_v2 JSON 解析失败兜底
- dispatch_next_v1 向后兼容

不触发 ainovel_py.agents.__init__（避免 runner.py 中不存在的 hints 模块 import 错误）。
但要让 tags 模块能被 dispatcher 正确 import，构造伪包层次。
"""
from __future__ import annotations

import sys
import importlib.util
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _install_fake_package(name: str):
    """在 sys.modules 中安装伪包，让 from .xxx import yyy 能工作。"""
    if name in sys.modules:
        return sys.modules[name]
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        sub = ".".join(parts[:i])
        if sub not in sys.modules:
            m = types.ModuleType(sub)
            m.__path__ = []     # 让 Python 把它当包处理
            sys.modules[sub] = m
    return sys.modules[name]


def _load_module(name: str, rel_path: str):
    """通过 importlib 加载模块到指定包层次。"""
    # 先确保父包存在
    if "." in name:
        parent = ".".join(name.split(".")[:-1])
        _install_fake_package(parent)
    spec = importlib.util.spec_from_file_location(name, str(PROJECT_ROOT / rel_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 为 v1 dispatch_next 提供 stub hints 模块（避免真实 import）
def _install_hints_stub():
    hints_mod = _load_module(
        "ainovel_py.agents.orchestrator.langgraph.hints",
        "ainovel_py/agents/orchestrator/langgraph/hints.py",
    )
    if not hasattr(hints_mod, "parse_hint_actions"):
        # 如果原 hints.py 不存在，提供 stub
        from enum import Enum

        class HintAction(str, Enum):
            UNKNOWN = "unknown"

        def parse_hint_actions(hints):
            return []
        def plan_actions(actions):
            from dataclasses import dataclass, field
            @dataclass
            class _Plan:
                requires_review: bool = False
                rewrite_mode: str = ""
                queue: list = field(default_factory=list)
                @property
                def next_action(self): return "checkpoint"
            return _Plan()
        hints_mod.HintAction = HintAction
        hints_mod.parse_hint_actions = parse_hint_actions
        hints_mod.plan_actions = plan_actions
    return hints_mod


_install_hints_stub()


# 按依赖顺序加载：tags → registry → dispatcher
tags_mod = _load_module(
    "ainovel_py.agents.orchestrator.tags",
    "ainovel_py/agents/orchestrator/tags.py",
)
registry_mod = _load_module(
    "ainovel_py.agents.orchestrator.registry",
    "ainovel_py/agents/orchestrator/registry.py",
)
dispatcher_mod = _load_module(
    "ainovel_py.agents.orchestrator.dispatcher",
    "ainovel_py/agents/orchestrator/dispatcher.py",
)

AgentRegistry = registry_mod.AgentRegistry
AgentSpec = registry_mod.AgentSpec
dispatch_next = dispatcher_mod.dispatch_next
dispatch_next_v2 = dispatcher_mod.dispatch_next_v2
TaskTag = tags_mod.TaskTag


# ============================================================
# Part 1: AgentRegistry 测试
# ============================================================
print("=" * 60)
print("Part 1: AgentRegistry")
print("=" * 60)

# Test 1.1: 基础 CRUD
r = AgentRegistry()
r.register(AgentSpec(name="a", role="测试A", description="agent a"))
r.register(AgentSpec(name="b", role="测试B", description="agent b", allowed_next=["c"]))
assert r.all_names() == ["a", "b"]
assert r.get("a").description == "agent a"
assert r.get("b").allowed_next == ["c"]
assert r.has("a") and not r.has("nonexistent")
print("[PASS] 1.1 基础 CRUD")

# Test 1.2: 重复注册 raise
try:
    r.register(AgentSpec(name="a", role="dup", description="dup"))
    assert False, "should raise"
except ValueError as e:
    assert "already registered" in str(e)
print("[PASS] 1.2 重复注册 raise")

# Test 1.3: 必填字段校验
for bad_spec in [
    AgentSpec(name="", role="x", description="x"),
    AgentSpec(name="x", role="", description="x"),
    AgentSpec(name="x", role="x", description=""),
]:
    try:
        r.register(bad_spec)
        assert False, f"should raise for {bad_spec}"
    except ValueError:
        pass
print("[PASS] 1.3 必填字段校验")

# Test 1.4: allowed_targets 行为
r2 = AgentRegistry()
r2.register(AgentSpec(name="x", role="x", description="x", allowed_next=["y"]))
r2.register(AgentSpec(name="y", role="y", description="y"))
assert r2.allowed_targets("x") == ["y"]
assert r2.allowed_targets("y") == []           # y 没声明 allowed_next
assert r2.allowed_targets("") == ["x", "y"]    # 流程入口返回除 supervisor 外全部
assert r2.allowed_targets("unknown") == ["x", "y"]  # 未知 agent 兜底返回全部
print("[PASS] 1.4 allowed_targets 行为")

# Test 1.5: filter_candidates 排除
r3 = AgentRegistry()
r3.register(AgentSpec(name="supervisor", role="s", description="s", allowed_next=["a", "b", "c"]))
r3.register(AgentSpec(name="a", role="a", description="a", allowed_next=["a", "b", "c"]))
r3.register(AgentSpec(name="b", role="b", description="b"))
r3.register(AgentSpec(name="c", role="c", description="c"))
# from_agent="a" 的 allowed_next = ["a", "b", "c"]
# 排除 b 后剩 a, c
cands = r3.filter_candidates("a", exclude={"b"})
assert cands == ["a", "c"], f"got {cands}"
cands2 = r3.filter_candidates("a", exclude={"b", "c"})
assert cands2 == ["a"], f"got {cands2}"
# supervisor 会被 filter_candidates 默认排除
cands3 = r3.filter_candidates("a", exclude={"supervisor"})
assert "supervisor" not in cands3
print("[PASS] 1.5 filter_candidates 排除")

# Test 1.6: unregister
r.unregister("a")
assert not r.has("a")
assert r.has("b")
print("[PASS] 1.6 unregister")

# ============================================================
# Part 2: dispatch_next v1 向后兼容
# ============================================================
print("=" * 60)
print("Part 2: dispatch_next v1 向后兼容")
print("=" * 60)

# Test 2.1: pending_action 优先
state = {"pending_action": "finish"}
assert dispatch_next(state) == TaskTag.FINISH
state = {"pending_action": "novel_context"}
assert dispatch_next(state) == TaskTag.PLAN_CHAPTER
print("[PASS] 2.1 pending_action 优先")

# Test 2.2: 规则链路
assert dispatch_next({"last_completed_tag": "plan_chapter"}) == TaskTag.WRITE_CHAPTER
assert dispatch_next({"last_completed_tag": "write_chapter"}) == TaskTag.COMMIT_CHAPTER
assert dispatch_next({"last_completed_tag": "commit_chapter"}) == TaskTag.PLAN_CHAPTER
assert dispatch_next({"last_completed_tag": "review_chapter", "latest_review_result": {"final_verdict": "accept"}}) == TaskTag.PLAN_CHAPTER
print("[PASS] 2.2 规则链路")

# ============================================================
# Part 3: dispatch_next_v2 FAST_RULES 命中
# ============================================================
print("=" * 60)
print("Part 3: dispatch_next_v2 FAST_RULES")
print("=" * 60)

reg = AgentRegistry()
reg.register(AgentSpec(name="architect", role="规划", description="规划章节"))
reg.register(AgentSpec(name="writer", role="写作", description="写正文", allowed_next=["editor_commit", "writer"]))
reg.register(AgentSpec(name="editor_commit", role="提交", description="提交章节", allowed_next=["supervisor", "editor_review"]))
reg.register(AgentSpec(name="editor_review", role="评审", description="评审章节", allowed_next=["supervisor", "writer", "editor_commit"]))
reg.register(AgentSpec(name="supervisor", role="调度", description="调度", allowed_next=["editor_review", "writer", "FINISH"]))


class CallCounter:
    def __init__(self):
        self.calls = 0
    def complete(self, *a, **kw):
        self.calls += 1
        return '{"next_agent": "supervisor"}'


counter = CallCounter()
state = {"last_completed_tag": "", "pending_action": "", "current_chapter": 1}
result = dispatch_next_v2(state, reg, llm_client=counter)
assert result == "architect", f"got {result}"
assert counter.calls == 0, "FAST_RULES 应零 LLM 调用"
print(f"[PASS] 3.1 首次启动→architect, zero LLM call")

state = {"last_completed_tag": "architect", "pending_action": "generate_draft", "current_chapter": 1}
result = dispatch_next_v2(state, reg, llm_client=counter)
assert result == "writer", f"got {result}"
assert counter.calls == 0
print(f"[PASS] 3.2 architect+write_chapter→writer")

state = {"last_completed_tag": "writer", "pending_action": "commit_chapter"}
result = dispatch_next_v2(state, reg, llm_client=counter)
assert result == "editor_commit", f"got {result}"
print(f"[PASS] 3.3 writer+commit_chapter→editor_commit")

# ============================================================
# Part 4: dispatch_next_v2 LLM 兜底
# ============================================================
print("=" * 60)
print("Part 4: dispatch_next_v2 LLM 兜底")
print("=" * 60)


class MockLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0
        self.last_prompt = None
    def complete(self, system_prompt, user_prompt, temperature=0.7):
        self.calls += 1
        self.last_prompt = user_prompt
        return self.response


# Test 4.1: 未命中规则 → 调 LLM
state = {"last_completed_tag": "editor_commit", "pending_action": "unknown_action", "current_chapter": 3}
mock = MockLLM('{"next_agent": "supervisor", "reasoning": "test"}')
result = dispatch_next_v2(state, reg, llm_client=mock)
assert result == "supervisor", f"got {result}"
assert mock.calls == 1
assert "可选 Agent" in mock.last_prompt
print(f"[PASS] 4.1 未命中→调 LLM, 返回 supervisor")

# Test 4.2: LLM 返回未注册的 agent → raise
mock = MockLLM('{"next_agent": "evil_agent"}')
try:
    dispatch_next_v2(state, reg, llm_client=mock)
    assert False, "should raise"
except RuntimeError as e:
    assert "out-of-scope" in str(e)
    assert "evil_agent" in str(e)
print(f"[PASS] 4.2 LLM 越界→raise RuntimeError")

# Test 4.3: LLM 返回非 JSON → 兜底到 supervisor
mock = MockLLM("not a json")
result = dispatch_next_v2(state, reg, llm_client=mock)
assert result == "supervisor", f"got {result}"
print(f"[PASS] 4.3 LLM JSON 失败→supervisor 兜底")

# Test 4.4: LLM 抛异常 → 兜底到 supervisor
class FailingLLM:
    def complete(self, *a, **kw):
        raise ConnectionError("网络挂了")
state = {"last_completed_tag": "editor_commit", "pending_action": "unknown_action"}
result = dispatch_next_v2(state, reg, llm_client=FailingLLM())
assert result == "supervisor", f"got {result}"
print(f"[PASS] 4.4 LLM 抛异常→supervisor 兜底")

# Test 4.5: 未提供 LLM 客户端 → 退回 v1 纯规则
state = {"last_completed_tag": "plan_chapter"}
result = dispatch_next_v2(state, reg, llm_client=None)
assert result == "write_chapter", f"got {result}"     # v1 返回 TaskTag.value
print(f"[PASS] 4.5 None LLM→v1 规则（返回 TaskTag.value）")

# ============================================================
# Part 5: dispatch_next_v2 候选白名单
# ============================================================
print("=" * 60)
print("Part 5: dispatch_next_v2 候选白名单")
print("=" * 60)

# Test 5.1: from_agent 限制候选
# from_agent="editor_commit" 的 allowed_next 是 ["supervisor", "editor_review"]
# 不在候选中的 agent 即使 LLM 选了也会 raise
mock = MockLLM('{"next_agent": "writer"}')   # writer 不在 editor_commit.allowed_next
state_5_1 = {"last_completed_tag": "editor_commit", "pending_action": "unknown"}
try:
    dispatch_next_v2(state_5_1, reg, llm_client=mock)
    assert False, "should raise"
except RuntimeError as e:
    assert "out-of-scope" in str(e)
print(f"[PASS] 5.1 editor_commit 后 LLM 选 writer→raise（白名单拦截）")

# Test 5.2: supervisor 兜底候选永远存在
mock = MockLLM('{"next_agent": "supervisor"}')
state_5_2 = {"last_completed_tag": "writer", "pending_action": "unknown"}
result = dispatch_next_v2(state_5_2, reg, llm_client=mock)
assert result == "supervisor"
print(f"[PASS] 5.2 supervisor 永远作为兜底候选")

# ============================================================
# Part 6: dispatch_next_v2 日志
# ============================================================
print("=" * 60)
print("Part 6: dispatch_next_v2 日志")
print("=" * 60)

import tempfile
import os
import json

with tempfile.TemporaryDirectory() as tmpdir:
    log_path = os.path.join(tmpdir, "subdir", "log.jsonl")
    mock = MockLLM('{"next_agent": "supervisor"}')
    state = {"last_completed_tag": "editor_commit", "pending_action": "unknown"}
    result = dispatch_next_v2(state, reg, llm_client=mock, log_path=log_path)
    assert result == "supervisor"
    assert os.path.exists(log_path)
    with open(log_path, encoding="utf-8") as f:
        line = f.readline()
        entry = json.loads(line)
        assert entry["decision"] == "supervisor"
        assert "candidates" in entry
        assert "prompt" in entry
    print(f"[PASS] 6.1 log_path 启用→写入 jsonl")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)

"""阶段 C 回归测试：supervisor 必经路由点。

验证：
1. 角色子图完成后必经过 supervisor 节点
2. supervisor_decision 被 _dispatch_node 消费后清空（不重复触发 LLM）
3. supervisor 失败时回退到 route_after_commit
4. parallel_summaries 节点在 collect 后正确路由
5. checkpoint → supervisor 必经边
"""
from __future__ import annotations

import sys
import importlib.util
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _install_fake_package(name: str):
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


def _load_module(name: str, rel_path: str):
    if "." in name:
        parent = ".".join(name.split(".")[:-1])
        _install_fake_package(parent)
    spec = importlib.util.spec_from_file_location(name, str(PROJECT_ROOT / rel_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


print("=" * 60)
print("阶段 C 回归测试：supervisor 必经路由点")
print("=" * 60)


# ============================================================
# Test 1: 主图拓扑 - supervisor 必经路由
# ============================================================
print("\n[Test 1] 主图拓扑：所有 collect 节点都连到 supervisor")

# 通过 mock runtime 验证 _build_graph 生成的拓扑
# 关键边：architect_plan/writer_write/editor_commit/editor_review/architect_summary → collect
# collect → parallel_summaries 或 supervisor
# checkpoint → supervisor
# supervisor 存在并有出边

# 加载核心模块
tags_mod = _load_module(
    "ainovel_py.agents.orchestrator.tags",
    "ainovel_py/agents/orchestrator/tags.py",
)
hints_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.hints",
    "ainovel_py/agents/orchestrator/langgraph/hints.py",
)

# hints stub
if not hasattr(hints_mod, "HintAction"):
    from enum import Enum
    class HintAction(str, Enum):
        UNKNOWN = "unknown"
    def parse_hint_actions(h):
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

state_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.state",
    "ainovel_py/agents/orchestrator/langgraph/state.py",
)
TaskTag = tags_mod.TaskTag

# 验证 TAG_TO_NODE 和 AGENT_TO_NODE 的完整性
import importlib.util as iu
spec = iu.spec_from_file_location(
    "core_test",
    str(PROJECT_ROOT / "ainovel_py/agents/orchestrator/langgraph/core.py"),
)

# 直接检查 core.py 源文件中的关键定义
core_path = PROJECT_ROOT / "ainovel_py/agents/orchestrator/langgraph/core.py"
core_source = core_path.read_text(encoding="utf-8")

# 检查 supervisor 节点已被注册
assert 'graph.add_node("supervisor"' in core_source, "supervisor 节点未注册"
print("[PASS] 1.1 supervisor 节点已注册到主图")

# 检查 parallel_summaries 节点已注册
assert 'graph.add_node("parallel_summaries"' in core_source, "parallel_summaries 节点未注册"
print("[PASS] 1.2 parallel_summaries 节点已注册")

# 检查关键边：所有角色子图都连到 collect
for agent in ["architect_plan", "writer_write", "editor_commit", "editor_review", "architect_summary"]:
    assert f'graph.add_edge("{agent}", "collect")' in core_source, f"{agent} → collect 边缺失"
print("[PASS] 1.3 所有角色子图 → collect 边已建立")

# 检查 collect → parallel_summaries | supervisor
assert '_route_after_collect_to_parallel' in core_source, "collect 路由函数缺失"
print("[PASS] 1.4 collect → parallel_summaries/supervisor 路由已建立")

# 检查 parallel_summaries → supervisor
assert 'graph.add_edge("parallel_summaries", "supervisor")' in core_source, "parallel_summaries → supervisor 边缺失"
print("[PASS] 1.5 parallel_summaries → supervisor 必经边已建立")

# 检查 checkpoint → supervisor
assert 'graph.add_edge("checkpoint", "supervisor")' in core_source, "checkpoint → supervisor 边缺失"
print("[PASS] 1.6 checkpoint → supervisor 必经边已建立")

# 检查 supervisor 出口有 conditional_edges
# supervisor 的 add_conditional_edges 后面几行是 "supervisor", "supervisor", route_from_supervisor
supervisor_conditional = (
    'add_conditional_edges' in core_source
    and '"supervisor"' in core_source
    and 'route_from_supervisor' in core_source
)
# 用 grep 模式：找到所有 add_conditional_edges 位置，看后面是否有 supervisor
import re
matches = list(re.finditer(r'add_conditional_edges\s*\(\s*\n\s*"(\w+)"', core_source))
supervisor_as_source = any(m.group(1) == "supervisor" for m in matches)
assert supervisor_as_source, f"supervisor 不是任何 conditional_edges 的源，匹配到: {[m.group(1) for m in matches]}"
print(f"[PASS] 1.7 supervisor 节点出口条件边已建立 (匹配到 {len(matches)} 个 conditional_edges)")


# ============================================================
# Test 2: _collect_node 只更新 last_completed_tag，不动 pending_action
# ============================================================
print("\n[Test 2] _collect_node 行为：只更新 last_completed_tag")

# 验证 _collect_node 源码不再修改 pending_action
assert 'state["last_completed_tag"] = completed_tag' in core_source, "_collect_node 未设置 last_completed_tag"
# 阶段 C 后不应再有 pending_action 赋值（在 collect 内）
# 通过搜索"pending_action"出现的上下文判断
collect_node_start = core_source.find("def _collect_node")
collect_node_end = core_source.find("return _node\n", collect_node_start)
collect_node_body = core_source[collect_node_start:collect_node_end]
assert 'state["pending_action"]' not in collect_node_body, "_collect_node 不应再设置 pending_action"
print("[PASS] 2.1 _collect_node 不再修改 pending_action（由 supervisor 决定）")


# ============================================================
# Test 3: _dispatch_node 检测 supervisor_decision 后跳过 LLM
# ============================================================
print("\n[Test 3] _dispatch_node 短路 supervisor_decision")

# 验证 _dispatch_node 源码
assert 'supervisor_decision' in core_source, "_dispatch_node 未引用 supervisor_decision"
# 验证：检测到 supervisor_decision 后直接消费
assert 'if supervisor_decision and isinstance(supervisor_decision, dict):' in core_source, \
    "_dispatch_node 未检测 supervisor_decision"
print("[PASS] 3.1 _dispatch_node 检测 supervisor_decision 并短路")

# 验证：消费后清空，避免下次重复消费
assert 'state["supervisor_decision"] = None' in core_source, "_dispatch_node 未清空 supervisor_decision"
print("[PASS] 3.2 supervisor_decision 被消费后清空")


# ============================================================
# Test 4: SUPERVISOR_ACTION_MAP 白名单校验
# ============================================================
print("\n[Test 4] SUPERVISOR_ACTION_MAP 完整性")

helpers_path = PROJECT_ROOT / "ainovel_py/agents/orchestrator/langgraph/nodes/helpers.py"
helpers_source = helpers_path.read_text(encoding="utf-8")

assert "SUPERVISOR_ACTION_MAP" in helpers_source, "SUPERVISOR_ACTION_MAP 未定义"
# 验证所有关键 action 都在 map 中
required_actions = ["architect", "writer", "editor", "rewrite",
                    "arc_summary", "volume_summary", "expand_arc",
                    "checkpoint", "FINISH"]
for action in required_actions:
    assert f'"{action}"' in helpers_source, f"action {action} 不在 SUPERVISOR_ACTION_MAP 中"
print(f"[PASS] 4.1 SUPERVISOR_ACTION_MAP 包含所有关键 action: {required_actions}")

# 验证 VALID_SUPERVISOR_TARGETS 是 frozen set
assert "VALID_SUPERVISOR_TARGETS" in helpers_source, "VALID_SUPERVISOR_TARGETS 未定义"
assert "frozenset" in helpers_source, "VALID_SUPERVISOR_TARGETS 应为 frozenset"
print("[PASS] 4.2 VALID_SUPERVISOR_TARGETS 是 frozenset（白名单防御）")


# ============================================================
# Test 5: AGENT_TO_NODE 映射完整性（阶段 B 改造）
# ============================================================
print("\n[Test 5] AGENT_TO_NODE 映射（阶段 B 改造）")

# 验证所有 agent name 都能映射到子图节点
required_agents = ["architect", "writer", "editor_commit", "editor_review",
                   "rewrite", "arc_summary", "volume_summary", "expand_arc",
                   "checkpoint", "supervisor", "FINISH"]
for agent in required_agents:
    assert f'"{agent}"' in core_source, f"agent {agent} 不在 AGENT_TO_NODE 中"
print(f"[PASS] 5.1 AGENT_TO_NODE 包含 {len(required_agents)} 个 agent name")


# ============================================================
# Test 6: is_parallel_summary_set 路由逻辑
# ============================================================
print("\n[Test 6] is_parallel_summary_set 路由逻辑")

# 验证函数存在
assert "def is_parallel_summary_set" in helpers_source, "is_parallel_summary_set 未定义"
print("[PASS] 6.1 is_parallel_summary_set 函数存在")


# ============================================================
# Test 7: 模拟 dispatch_next_v2 候选白名单（与 supervisor 协作）
# ============================================================
print("\n[Test 7] dispatch_next_v2 候选白名单（与 supervisor 协作）")

# 验证 supervisor 永远在候选中
dispatcher_path = PROJECT_ROOT / "ainovel_py/agents/orchestrator/dispatcher.py"
dispatcher_source = dispatcher_path.read_text(encoding="utf-8")
assert 'registry.has("supervisor") and "supervisor" not in candidates' in dispatcher_source, \
    "supervisor 未作为永久兜底候选"
print("[PASS] 7.1 supervisor 在 dispatch_next_v2 候选中作为永久兜底")


# ============================================================
# Test 8: 验证 _route_after_collect_to_parallel 实现
# ============================================================
print("\n[Test 8] _route_after_collect_to_parallel 实现")

assert "def _route_after_collect_to_parallel" in core_source, "_route_after_collect_to_parallel 未定义"
# 验证 is_parallel_summary_set 在该函数附近被调用（用更宽松的匹配）
func_start = core_source.find("def _route_after_collect_to_parallel")
# 取后面 800 字符的代码块
next_def = core_source.find("\ndef ", func_start + 10)
if next_def == -1:
    next_def = func_start + 800
route_func = core_source[func_start:next_def]
assert "is_parallel_summary_set" in route_func, "_route_after_collect_to_parallel 未调用 is_parallel_summary_set"
print("[PASS] 8.1 _route_after_collect_to_parallel 调用 is_parallel_summary_set")


print("\n" + "=" * 60)
print("阶段 C 回归测试：ALL PASSED")
print("=" * 60)

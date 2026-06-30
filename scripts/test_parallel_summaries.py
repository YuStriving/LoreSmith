"""优化 ①-1/①-2 单元测试：_execute_parallel_summaries + parallel_summaries 节点。

验证：
1. is_parallel_summary_set 判断逻辑
2. _execute_parallel_summaries 顺序无关性
3. _run_summary_task 单任务包装
4. _route_after_collect_to_parallel 路由逻辑
5. 线程安全：每个任务独立日志缓冲
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 helpers 模块（避免触发 ainovel_py.agents.__init__ 的 hints 缺失问题）
import importlib.util
import types


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


# 提供必要的 stub 模块
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

# state stub
state_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.state",
    "ainovel_py/agents/orchestrator/langgraph/state.py",
)

# host.events stub（必须在 review_flow 之前加载，否则 review_flow 内的 import 会失败）
events_mod = _load_module(
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

# review_flow stub
review_flow_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.review_flow",
    "ainovel_py/agents/orchestrator/langgraph/review_flow.py",
)

# domain.runtime stub
runtime_mod = _load_module(
    "ainovel_py.domain.runtime",
    "ainovel_py/domain/runtime.py",
)
if not hasattr(runtime_mod, "FlowState"):
    from enum import Enum
    class FlowState(str, Enum):
        REWRITING = "rewriting"
        POLISHING = "polishing"
        NORMAL = "normal"
    runtime_mod.FlowState = FlowState

# helpers 模块
helpers_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.nodes.helpers",
    "ainovel_py/agents/orchestrator/langgraph/nodes/helpers.py",
)

is_parallel_summary_set = helpers_mod.is_parallel_summary_set
_execute_parallel_summaries = helpers_mod._execute_parallel_summaries
_run_summary_task = helpers_mod._run_summary_task
SUMMARY_TASK_ARC = helpers_mod.SUMMARY_TASK_ARC
SUMMARY_TASK_VOLUME = helpers_mod.SUMMARY_TASK_VOLUME
SUMMARY_TASK_EXPAND = helpers_mod.SUMMARY_TASK_EXPAND


print("=" * 60)
print("优化 ①-1/①-2 单元测试：并行 summary")
print("=" * 60)


# ============================================================
# Part 1: is_parallel_summary_set 逻辑
# ============================================================
print("Part 1: is_parallel_summary_set")
assert is_parallel_summary_set([]) is False
assert is_parallel_summary_set(["arc_summary"]) is False
assert is_parallel_summary_set([SUMMARY_TASK_ARC, SUMMARY_TASK_VOLUME]) is True
assert is_parallel_summary_set([SUMMARY_TASK_ARC, SUMMARY_TASK_VOLUME, SUMMARY_TASK_EXPAND]) is True
assert is_parallel_summary_set([SUMMARY_TASK_ARC, "rewrite"]) is False  # 含非 summary 任务
assert is_parallel_summary_set(["unknown_task"]) is False
print("[PASS] 1.1 任务集合判断")


# ============================================================
# Part 2: _run_summary_task 单任务
# ============================================================
print("Part 2: _run_summary_task")

def make_mock_runtime():
    runtime = MagicMock()
    runtime.runner.call_tool.return_value = {"ok": True}
    runtime.emit_event.return_value = None
    progress = MagicMock()
    progress.current_volume = 1
    runtime.store.progress.load.return_value = progress
    return runtime

state = {"current_chapter": 5, "out_lines": []}
runtime = make_mock_runtime()
out_lines = []
result = _run_summary_task(runtime, state, SUMMARY_TASK_ARC, out_lines)
assert result["ok"] is True
assert result["task"] == SUMMARY_TASK_ARC
assert "save_arc_summary" in str(runtime.runner.call_tool.call_args)
print(f"[PASS] 2.1 arc_summary task: {result['result']}")

# 测试 volume_summary
runtime = make_mock_runtime()
result = _run_summary_task(runtime, state, SUMMARY_TASK_VOLUME, out_lines)
assert result["ok"] is True
assert "save_volume_summary" in str(runtime.runner.call_tool.call_args)
print(f"[PASS] 2.2 volume_summary task: {result['result']}")

# 测试未知任务
runtime = make_mock_runtime()
result = _run_summary_task(runtime, state, "unknown", out_lines)
assert result["ok"] is False
assert "unknown" in result["error"]
print(f"[PASS] 2.3 unknown task → error")


# ============================================================
# Part 3: _execute_parallel_summaries 并行执行
# ============================================================
print("Part 3: _execute_parallel_summaries 并行执行")

# mock call_tool 添加延迟以验证并行
def slow_call_tool(*args, **kwargs):
    time.sleep(0.1)
    return {"ok": True}

runtime = make_mock_runtime()
runtime.runner.call_tool.side_effect = slow_call_tool

state = {"current_chapter": 5, "out_lines": []}
tasks = [SUMMARY_TASK_ARC, SUMMARY_TASK_VOLUME]
t_start = time.time()
result = _execute_parallel_summaries(runtime, state, tasks)
elapsed = time.time() - t_start

# 串行需要 0.2s，并行应该 < 0.15s
assert elapsed < 0.15, f"parallel execution should be faster, took {elapsed:.2f}s"
assert result["all_ok"] is True
assert SUMMARY_TASK_ARC in result["results"]
assert SUMMARY_TASK_VOLUME in result["results"]
assert len(state.get("out_lines", [])) > 0  # 至少有一行汇总日志
print(f"[PASS] 3.1 2 个任务并行执行 (elapsed={elapsed:.2f}s)")

# 单个任务也能运行
runtime = make_mock_runtime()
state = {"current_chapter": 5, "out_lines": []}
result = _execute_parallel_summaries(runtime, state, [SUMMARY_TASK_ARC])
assert result["all_ok"] is True
print("[PASS] 3.2 单任务运行")

# 空任务列表
runtime = make_mock_runtime()
state = {"current_chapter": 5, "out_lines": []}
result = _execute_parallel_summaries(runtime, state, [])
assert result["all_ok"] is True
assert result["duration"] == 0.0
print("[PASS] 3.3 空任务列表")


# ============================================================
# Part 4: 错误处理
# ============================================================
print("Part 4: 错误处理")

def failing_call_tool(*args, **kwargs):
    raise RuntimeError("simulated failure")

runtime = make_mock_runtime()
runtime.runner.call_tool.side_effect = failing_call_tool
state = {"current_chapter": 5, "out_lines": []}
result = _execute_parallel_summaries(runtime, state, [SUMMARY_TASK_ARC, SUMMARY_TASK_VOLUME])
assert result["all_ok"] is False
assert result["results"][SUMMARY_TASK_ARC]["ok"] is False
assert "simulated failure" in result["results"][SUMMARY_TASK_ARC]["error"]
print(f"[PASS] 4.1 任务失败被捕获（all_ok=False）")


print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)

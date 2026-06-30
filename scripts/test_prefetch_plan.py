"""优化 ③ 单元测试：跨章预规划 (PrefetchPlanCache + writer_subgraph + architect_subgraph)。

验证：
1. PrefetchPlanCache 基础读写
2. mark_pending / unmark_pending 重复保护
3. 线程安全：并发读写
4. 落盘：从 JSON 文件恢复
5. trigger_prefetch_plan 后台提交 + 命中验证
6. writer_subgraph 含 trigger_prefetch 节点
7. architect_subgraph 命中缓存时跳过 LLM
8. architect_subgraph 未命中时正常 LLM 调用
9. 端到端：写 N 章 → 预规划 N+1 → 规划 N+1 命中
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

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


# ============================================================
# 加载依赖 stub
# ============================================================
tags_mod = _load_module(
    "ainovel_py.agents.orchestrator.tags",
    "ainovel_py/agents/orchestrator/tags.py",
)
hints_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.hints",
    "ainovel_py/agents/orchestrator/langgraph/hints.py",
)
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

review_flow_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.review_flow",
    "ainovel_py/agents/orchestrator/langgraph/review_flow.py",
)

runtime_mod = _load_module(
    "ainovel_py.domain.runtime",
    "ainovel_py/domain/runtime.py",
)
FlowState = runtime_mod.FlowState
NORMAL_FLOW = getattr(FlowState, "WRITING", None) or getattr(FlowState, "NORMAL", None) or "writing"

helpers_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.nodes.helpers",
    "ainovel_py/agents/orchestrator/langgraph/nodes/helpers.py",
)

# prefetch 模块
prefetch_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.prefetch",
    "ainovel_py/agents/orchestrator/langgraph/prefetch.py",
)

# writer_subgraph
writer_subgraph_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.subgraphs.writer_subgraph",
    "ainovel_py/agents/orchestrator/langgraph/subgraphs/writer_subgraph.py",
)

# architect_subgraph
architect_subgraph_mod = _load_module(
    "ainovel_py.agents.orchestrator.langgraph.subgraphs.architect_subgraph",
    "ainovel_py/agents/orchestrator/langgraph/subgraphs/architect_subgraph.py",
)


PrefetchPlanCache = prefetch_mod.PrefetchPlanCache
get_runtime_cache = prefetch_mod.get_runtime_cache
reset_runtime_cache = prefetch_mod.reset_runtime_cache
trigger_prefetch_plan = prefetch_mod.trigger_prefetch_plan

_build_plan_node = architect_subgraph_mod._build_plan_node
_trigger_prefetch_node = writer_subgraph_mod._trigger_prefetch_node


print("=" * 60)
print("优化 ③ 单元测试：跨章预规划")
print("=" * 60)


# ============================================================
# Part 1: PrefetchPlanCache 基础读写
# ============================================================
print("Part 1: PrefetchPlanCache 基础读写")
cache = PrefetchPlanCache()
assert cache.size() == 0
assert cache.get(1) is None
assert cache.has(1) is False

cache.put(1, {"chapter": 1, "title": "第一章", "goal": "起"})
assert cache.has(1) is True
assert cache.get(1) == {"chapter": 1, "title": "第一章", "goal": "起"}
assert cache.size() == 1
print("[PASS] 1.1 put/get/has/size")

cache.put(2, {"chapter": 2, "title": "第二章"})
assert cache.size() == 2
assert cache.all_chapters() == [1, 2]
print("[PASS] 1.2 多章节存储")

cache.clear()
assert cache.size() == 0
print("[PASS] 1.3 clear")


# ============================================================
# Part 2: mark_pending 重复保护
# ============================================================
print("Part 2: mark_pending 重复保护")
cache = PrefetchPlanCache()
# 第一次标记应成功
ok1 = cache.mark_pending(5)
assert ok1 is True
assert cache.is_pending(5) is True
# 第二次标记应失败（已在 pending）
ok2 = cache.mark_pending(5)
assert ok2 is False
print("[PASS] 2.1 重复 mark_pending 被拒绝")

# 写入后不应再能 mark_pending
cache.put(5, {"chapter": 5, "title": "第五章"})
ok3 = cache.mark_pending(5)
assert ok3 is False
print("[PASS] 2.2 已存在的 chapter 不能再次 mark_pending")

# unmark_pending 之后可以重新标记
cache.unmark_pending(7)
ok4 = cache.mark_pending(7)
assert ok4 is True
print("[PASS] 2.3 unmark_pending 后可重新标记")


# ============================================================
# Part 3: 线程安全
# ============================================================
print("Part 3: 线程安全")
cache = PrefetchPlanCache()
errors: list[Exception] = []


def writer_worker(start: int):
    try:
        for i in range(100):
            cache.put(start + i, {"chapter": start + i, "title": f"ch{start + i}"})
    except Exception as exc:
        errors.append(exc)


def reader_worker():
    try:
        for _ in range(200):
            cache.get(1)
            cache.has(2)
            cache.size()
            cache.all_chapters()
    except Exception as exc:
        errors.append(exc)


threads = [
    threading.Thread(target=writer_worker, args=(0,)),
    threading.Thread(target=writer_worker, args=(1000,)),
    threading.Thread(target=reader_worker),
    threading.Thread(target=reader_worker),
]
for t in threads:
    t.start()
for t in threads:
    t.join()

assert not errors, f"线程安全错误: {errors}"
assert cache.size() == 200
print(f"[PASS] 3.1 4 线程并发读写 size={cache.size()}")


# ============================================================
# Part 4: 落盘 / 加载
# ============================================================
print("Part 4: 落盘 / 加载")
import json
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    io_path = Path(tmpdir) / ".prefetch.json"
    cache1 = PrefetchPlanCache(io_path=str(io_path))
    cache1.put(10, {"chapter": 10, "title": "第十章"})
    cache1.put(11, {"chapter": 11, "title": "第十一章"})
    # 强制落盘（put 时已自动落盘一次）
    assert io_path.exists()
    print("[PASS] 4.1 写入自动落盘")

    # 重新加载
    cache2 = PrefetchPlanCache(io_path=str(io_path))
    assert cache2.has(10)
    assert cache2.has(11)
    assert cache2.get(10) == {"chapter": 10, "title": "第十章"}
    print("[PASS] 4.2 从落盘文件恢复")

    # 损坏文件不致命
    io_path.write_text("not valid json{", encoding="utf-8")
    cache3 = PrefetchPlanCache(io_path=str(io_path))
    assert cache3.size() == 0
    print("[PASS] 4.3 损坏文件降级为空缓存")


# ============================================================
# Part 5: get_runtime_cache 单例
# ============================================================
print("Part 5: get_runtime_cache 单例")
reset_runtime_cache(runtime := MagicMock())
c1 = get_runtime_cache(runtime)
c2 = get_runtime_cache(runtime)
assert c1 is c2
print("[PASS] 5.1 同一 runtime 拿到同一 cache")

# 不同 runtime 拿到的 cache 相互独立
other = MagicMock()
c3 = get_runtime_cache(other)
assert c3 is not c1
print("[PASS] 5.2 不同 runtime 拿不同 cache")

# 5.3 防御：MagicMock 自动属性（cfg.workspace_dir 是 mock）不能被误当作真实 io_path
#       否则会污染出 <MagicMock id='...'> 这样的乱目录
reset_runtime_cache(runtime := MagicMock())
c4 = get_runtime_cache(runtime)
# 即使 MagicMock 自动返回子 mock，校验后 io_path 必须为 None（纯内存）
assert c4._io_path is None, f"未校验 workspace_dir 类型，io_path={c4._io_path!r}"
# 写入不应创建任何文件
c4.put(1, {"chapter": 1, "title": "x"})
project_root = Path(__file__).resolve().parent.parent
polluted_dirs = [p for p in project_root.glob("MagicMock*") if p.exists()]
assert not polluted_dirs, f"被污染的目录: {polluted_dirs}"
print("[PASS] 5.3 MagicMock 防御：get_runtime_cache 不会污染文件系统")

reset_runtime_cache(runtime)
reset_runtime_cache(other)


def make_runtime_with_architect(slow_seconds: float = 0.05):
    """构造一个带 architect 模拟的 runtime，模拟 LLM 延迟。"""
    runtime = MagicMock()
    runtime.emit_event.return_value = None

    progress = MagicMock()
    progress.flow = NORMAL_FLOW
    progress.total_chapters = 0
    progress.pending_rewrites = []
    runtime.store.progress.load.return_value = progress

    architect = MagicMock()
    def slow_build(seed_text, chapter, context, feedback):
        time.sleep(slow_seconds)
        return {
            "chapter": chapter,
            "title": f"第{chapter}章",
            "goal": f"prefetched goal for ch{chapter}",
            "conflict": "prefetched conflict",
            "hook": "prefetched hook",
            "emotion_arc": "prefetched arc",
            "contract": {"min_words": 1200, "target_words": 1800, "max_words": 2600},
        }
    architect.build_dynamic_plan = slow_build
    runtime.get_agent.return_value = architect
    runtime.runner.call_tool.return_value = {"ok": True}
    return runtime


# ============================================================
# Part 6: trigger_prefetch_plan 后台提交
# ============================================================
print("Part 6: trigger_prefetch_plan 后台提交")
reset_runtime_cache(runtime := make_runtime_with_architect(slow_seconds=0.05))
ok = trigger_prefetch_plan(runtime, 8, "seed text")
assert ok is True
# 后台是 daemon 线程，最多等 2s
deadline = time.time() + 2.0
while time.time() < deadline:
    if get_runtime_cache(runtime).has(8):
        break
    time.sleep(0.02)
assert get_runtime_cache(runtime).has(8), "后台预规划未在 2s 内完成"
plan = get_runtime_cache(runtime).get(8)
assert plan["chapter"] == 8
assert plan["title"] == "第8章"
print("[PASS] 6.1 后台预规划成功完成")

# 6.2 重复提交被去重
ok2 = trigger_prefetch_plan(runtime, 8, "seed text")
assert ok2 is False, "重复触发应被拒绝"
print("[PASS] 6.2 重复 trigger 去重")

# 6.3 不同章节不互相影响
ok3 = trigger_prefetch_plan(runtime, 9, "seed text")
assert ok3 is True
deadline = time.time() + 2.0
while time.time() < deadline:
    if get_runtime_cache(runtime).has(9):
        break
    time.sleep(0.02)
assert get_runtime_cache(runtime).has(9)
print("[PASS] 6.3 不同章节独立预规划")

# 6.4 非法 chapter 被拒
ok4 = trigger_prefetch_plan(runtime, 0, "")
assert ok4 is False
ok5 = trigger_prefetch_plan(runtime, -1, "")
assert ok5 is False
print("[PASS] 6.4 非法 chapter 拒绝提交")

# 6.5 后台异常：unmark_pending + 缓存里没该章
reset_runtime_cache(runtime_bad := make_runtime_with_architect(slow_seconds=0.0))
def boom(*a, **k):
    raise RuntimeError("architect boom")
runtime_bad.get_agent.return_value.build_dynamic_plan = boom
trigger_prefetch_plan(runtime_bad, 100, "seed")
deadline = time.time() + 2.0
while time.time() < deadline:
    if not get_runtime_cache(runtime_bad).is_pending(100):
        break
    time.sleep(0.02)
assert not get_runtime_cache(runtime_bad).has(100)
assert not get_runtime_cache(runtime_bad).is_pending(100)
print("[PASS] 6.5 后台异常 → unmark_pending + 缓存无值")


# ============================================================
# Part 7: writer_subgraph.trigger_prefetch_node
# ============================================================
print("Part 7: writer_subgraph.trigger_prefetch_node")

# 7.1 正常情况：触发
reset_runtime_cache(runtime := make_runtime_with_architect(slow_seconds=0.02))
node = _trigger_prefetch_node(runtime)
state = {"current_chapter": 3, "seed_text": "seed"}
out = node(state)
assert "writer" in (out.get("out_lines") or [""])[-1] or "trigger_prefetch" in (out.get("out_lines") or [""])[-1]
# 验证后台上场
deadline = time.time() + 2.0
while time.time() < deadline:
    if get_runtime_cache(runtime).has(4):
        break
    time.sleep(0.02)
assert get_runtime_cache(runtime).has(4)
print("[PASS] 7.1 正常章节触发预规划")

# 7.2 rewrite 模式：跳过
reset_runtime_cache(runtime := make_runtime_with_architect())
node = _trigger_prefetch_node(runtime)  # 重新绑定到新 runtime
runtime.store.progress.load.return_value.flow = FlowState.REWRITING
runtime.store.progress.load.return_value.pending_rewrites = [3]
state = {"current_chapter": 3, "seed_text": "seed"}
out = node(state)
last_line = (out.get("out_lines") or [""])[-1]
assert "rewrite mode" in last_line
print("[PASS] 7.2 rewrite 模式跳过预规划")

# 7.3 已达总章节数：跳过
reset_runtime_cache(runtime := make_runtime_with_architect())
node = _trigger_prefetch_node(runtime)  # 重新绑定到新 runtime
runtime.store.progress.load.return_value.flow = NORMAL_FLOW
runtime.store.progress.load.return_value.total_chapters = 3
state = {"current_chapter": 3, "seed_text": "seed"}
out = node(state)
last_line = (out.get("out_lines") or [""])[-1]
assert "total" in last_line
print("[PASS] 7.3 达到 total_chapters 跳过")


# ============================================================
# Part 8: architect_subgraph.build_plan_node 缓存命中
# ============================================================
print("Part 8: architect_subgraph.build_plan_node 缓存命中")

# 8.1 命中：跳过 LLM
reset_runtime_cache(runtime := MagicMock())
events: list = []
runtime.emit_event.side_effect = lambda e: events.append(e)
runtime.store.progress.load.return_value = MagicMock(flow=NORMAL_FLOW, pending_rewrites=[])

# 预置缓存
get_runtime_cache(runtime).put(6, {"chapter": 6, "title": "预规划第六章", "goal": "x"})

# architect agent 不应被调用
runtime.get_agent.return_value = MagicMock()
node = _build_plan_node(runtime)
state = {"current_chapter": 6, "seed_text": "seed", "plan_feedback": ""}
out = node(state)
assert out["latest_plan_cache_hit"] is True
assert out["latest_plan"]["title"] == "预规划第六章"
# 关键验证：architect 没被实例化
runtime.get_agent.assert_not_called()
print("[PASS] 8.1 缓存命中 → 跳过 LLM")

# 8.2 未命中：正常 LLM
reset_runtime_cache(runtime := MagicMock())
runtime.store.progress.load.return_value = MagicMock(flow=NORMAL_FLOW, pending_rewrites=[])
architect = MagicMock()
architect.build_dynamic_plan.return_value = {"chapter": 6, "title": "LLM 生成"}
runtime.get_agent.return_value = architect
runtime.runner.call_tool.return_value = {"plan": {"chapter": 6, "title": "LLM 生成"}}
runtime.emit_event.return_value = None

node = _build_plan_node(runtime)
state = {"current_chapter": 6, "seed_text": "seed", "plan_feedback": ""}
out = node(state)
assert out["latest_plan_cache_hit"] is False
assert out["latest_plan"]["title"] == "LLM 生成"
architect.build_dynamic_plan.assert_called_once()
print("[PASS] 8.2 缓存未命中 → 走 LLM")

# 8.3 有 feedback：强制走 LLM
reset_runtime_cache(runtime := MagicMock())
runtime.store.progress.load.return_value = MagicMock(flow=NORMAL_FLOW, pending_rewrites=[])
get_runtime_cache(runtime).put(6, {"chapter": 6, "title": "缓存值"})
architect = MagicMock()
architect.build_dynamic_plan.return_value = {"chapter": 6, "title": "反馈生成"}
runtime.get_agent.return_value = architect
runtime.runner.call_tool.return_value = {"plan": {"chapter": 6, "title": "反馈生成"}}
runtime.emit_event.return_value = None
node = _build_plan_node(runtime)
state = {"current_chapter": 6, "seed_text": "seed", "plan_feedback": "用户反馈：要加入悬疑"}
out = node(state)
assert out["latest_plan_cache_hit"] is False
assert out["latest_plan"]["title"] == "反馈生成"
print("[PASS] 8.3 有 plan_feedback → 强制 LLM")


# ============================================================
# Part 9: 端到端 - 写 N 章 → 预规划 N+1 → 规划 N+1 命中
# ============================================================
print("Part 9: 端到端流水线")

reset_runtime_cache(runtime := make_runtime_with_architect(slow_seconds=0.05))
events.clear()
runtime.emit_event.side_effect = lambda e: events.append(e)
runtime.store.progress.load.return_value = MagicMock(flow=NORMAL_FLOW, total_chapters=0, pending_rewrites=[])

# 写完第 5 章后，预规划第 6 章
trigger_node = _trigger_prefetch_node(runtime)
state_after_write = {"current_chapter": 5, "seed_text": "端到端 seed"}
out = trigger_node(state_after_write)
assert get_runtime_cache(runtime).is_pending(6) or get_runtime_cache(runtime).has(6)

# 等后台完成
deadline = time.time() + 2.0
while time.time() < deadline:
    if get_runtime_cache(runtime).has(6):
        break
    time.sleep(0.02)
assert get_runtime_cache(runtime).has(6)
print("[PASS] 9.1 写 N 触发 N+1 预规划完成")

# 第 6 章 architect 节点被调起时，直接命中
# 注：用全新的 MagicMock runtime（避免被 prefetch 后台线程污染 call_count）
reset_runtime_cache(plan_runtime := MagicMock())
plan_runtime.emit_event.return_value = None
plan_runtime.store.progress.load.return_value = MagicMock(flow=NORMAL_FLOW, pending_rewrites=[])
# 把上一个 runtime 缓存里 ch6 的 plan 同步过来
saved_plan = get_runtime_cache(runtime).get(6)
get_runtime_cache(plan_runtime).put(6, saved_plan)

plan_node = _build_plan_node(plan_runtime)
state6 = {"current_chapter": 6, "seed_text": "端到端 seed", "plan_feedback": ""}
out = plan_node(state6)
assert out["latest_plan_cache_hit"] is True
# 关键：architect LLM 没被调用
plan_runtime.get_agent.assert_not_called()
# 日志包含 prefetch HIT
last_line = (out.get("out_lines") or [""])[-1]
assert "prefetch HIT" in last_line
print("[PASS] 9.2 architect 命中缓存（无 LLM）")


print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)

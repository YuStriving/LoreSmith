"""PrefetchPlanCache 单测。

覆盖：
1. 基础 get/put/has/clear/size
2. mark_pending / unmark_pending / is_pending 状态机
3. 重复 mark_pending 返回 False
4. 线程安全（多线程并发 put/get 不出错）
5. 落盘到 io_path 后从磁盘恢复
6. 损坏的 io_path 不致命（空缓存兜底）
7. MagicMock 防御（get_runtime_cache 不会把 MagicMock 当目录）
8. reset_runtime_cache
9. trigger_prefetch_plan 行为（已存在/已在 pending 时返回 False）
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ainovel_py.agents.orchestrator.langgraph.prefetch import (
    PrefetchPlanCache,
    RUNTIME_CACHE_ATTR,
    get_runtime_cache,
    reset_runtime_cache,
    trigger_prefetch_plan,
)


# ---------- 1. 基础 get/put/has/clear/size ----------

def test_get_miss_returns_none():
    cache = PrefetchPlanCache()
    assert cache.get(1) is None
    assert not cache.has(1)
    assert cache.size() == 0


def test_put_and_get():
    cache = PrefetchPlanCache()
    plan = {"chapter": 1, "title": "测试章"}
    cache.put(1, plan)
    assert cache.get(1) == plan
    assert cache.has(1)
    assert cache.size() == 1


def test_put_overwrites_existing():
    cache = PrefetchPlanCache()
    cache.put(1, {"title": "first"})
    cache.put(1, {"title": "second"})
    assert cache.get(1) == {"title": "second"}


def test_clear_resets_state():
    cache = PrefetchPlanCache()
    cache.put(1, {"title": "a"})
    cache.put(2, {"title": "b"})
    cache.clear()
    assert cache.size() == 0
    assert cache.get(1) is None


def test_all_chapters_returns_sorted_keys():
    cache = PrefetchPlanCache()
    cache.put(3, {})
    cache.put(1, {})
    cache.put(2, {})
    assert cache.all_chapters() == [1, 2, 3]


# ---------- 2. mark_pending 状态机 ----------

def test_mark_pending_succeeds_first_time():
    cache = PrefetchPlanCache()
    assert cache.mark_pending(1) is True
    assert cache.is_pending(1)


def test_mark_pending_returns_false_if_already_planned():
    cache = PrefetchPlanCache()
    cache.put(1, {"title": "x"})
    assert cache.mark_pending(1) is False


def test_mark_pending_returns_false_if_already_pending():
    cache = PrefetchPlanCache()
    cache.mark_pending(1)
    assert cache.mark_pending(1) is False


def test_unmark_pending():
    cache = PrefetchPlanCache()
    cache.mark_pending(1)
    cache.unmark_pending(1)
    assert not cache.is_pending(1)


# ---------- 3. 线程安全 ----------

def test_concurrent_put_and_get_no_errors():
    cache = PrefetchPlanCache()
    errors: list[Exception] = []

    def writer(ch: int) -> None:
        try:
            for _ in range(50):
                cache.put(ch, {"title": f"ch{ch}-{_}"})
        except Exception as e:
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(50):
                cache.get(1)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(1, 6)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert cache.size() == 5  # 5 个章节


# ---------- 4. 落盘与恢复 ----------

def test_persist_and_reload_from_disk(tmp_path: Path):
    io = tmp_path / "cache.json"
    cache1 = PrefetchPlanCache(io_path=io)
    cache1.put(1, {"title": "ch1"})
    cache1.put(2, {"title": "ch2"})

    cache2 = PrefetchPlanCache(io_path=io)
    assert cache2.get(1) == {"title": "ch1"}
    assert cache2.get(2) == {"title": "ch2"}


# ---------- 5. 损坏 io_path 兜底 ----------

def test_corrupt_io_path_returns_empty_cache(tmp_path: Path):
    io = tmp_path / "cache.json"
    io.write_text("not valid json {{{", encoding="utf-8")
    cache = PrefetchPlanCache(io_path=io)
    assert cache.size() == 0  # 损坏不致命


def test_io_path_with_int_key_in_json_skipped(tmp_path: Path):
    """JSON 中 keys 是字符串，转 int 失败时跳过。"""
    import json
    io = tmp_path / "cache.json"
    io.write_text(json.dumps({"plans": {"not-a-number": {}}}), encoding="utf-8")
    cache = PrefetchPlanCache(io_path=io)
    assert cache.size() == 0  # 非数字 key 被跳过


# ---------- 6. MagicMock 防御 ----------

def test_get_runtime_cache_ignores_magicmock_workspace_dir():
    """cfg.workspace_dir 是 MagicMock 时不创建乱目录。"""
    runtime = MagicMock()
    cfg = MagicMock()
    cfg.workspace_dir = MagicMock()  # 故意是 MagicMock
    runtime.cfg = cfg

    cache = get_runtime_cache(runtime)
    assert isinstance(cache, PrefetchPlanCache)
    # 关键：MagicMock 不应被当成目录名
    # cache._io_path 应该是 None（没把 MagicMock 当成路径）
    assert cache._io_path is None


def test_get_runtime_cache_uses_string_workspace_dir(tmp_path: Path):
    """cfg.workspace_dir 是字符串路径时正确落盘路径。"""
    runtime = MagicMock()
    cfg = MagicMock()
    cfg.workspace_dir = str(tmp_path)  # 字符串路径
    runtime.cfg = cfg

    cache = get_runtime_cache(runtime)
    expected = str(Path(tmp_path) / ".prefetch_plan.json")
    assert str(cache._io_path) == expected


# ---------- 7. reset_runtime_cache ----------

def test_reset_runtime_cache_clears_attr():
    runtime = MagicMock()
    runtime.cfg = MagicMock(workspace_dir=None)
    # 第一次创建
    cache1 = get_runtime_cache(runtime)
    setattr(runtime, RUNTIME_CACHE_ATTR, cache1)
    # 重置
    reset_runtime_cache(runtime)
    # 重新获取 → 新实例
    cache2 = get_runtime_cache(runtime)
    assert cache2 is not cache1


# ---------- 8. trigger_prefetch_plan 行为 ----------

def test_trigger_prefetch_plan_returns_false_for_non_positive_chapter():
    runtime = MagicMock()
    runtime.cfg = MagicMock(workspace_dir=None)
    assert trigger_prefetch_plan(runtime, next_chapter=0, seed_text="") is False
    assert trigger_prefetch_plan(runtime, next_chapter=-1, seed_text="") is False


def test_trigger_prefetch_plan_returns_false_when_already_planned():
    runtime = MagicMock()
    runtime.cfg = MagicMock(workspace_dir=None)
    cache = get_runtime_cache(runtime)
    cache.put(5, {"title": "already"})

    # 已存在 → 不再触发
    assert trigger_prefetch_plan(runtime, next_chapter=5, seed_text="") is False

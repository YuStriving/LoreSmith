"""优化 ③：跨章预规划缓存。

设计动机：
- 主流程里，writer 写完 N 章之后，下一步要调 architect 规划 N+1 章。
  N+1 的规划调用要等 LLM，是串行开销。
- 优化目标：在写 N 章的"等待 + 流式输出"窗口里，后台线程并发把 N+1 的规划算出来。
  等到 architect 节点被调起时，直接查缓存，命中就跳过 LLM 调用。

线程安全：
- prefetch 后台线程 + 主线程并发读写同一个缓存
- 内部用 threading.Lock 保护 _plans 字典 + _pending 状态

落盘（可选）：
- 构造时传入 io_path 后，每次写入会同步刷新到 JSON
- 用于在断电/重启后恢复预规划结果，避免重复 LLM
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any


class PrefetchPlanCache:
    """跨章预规划缓存：键=章节号，值=plan dict。

    典型用法：
        cache = PrefetchPlanCache()
        cache.put(7, plan_dict)
        ...
        cached = cache.get(7)
        if cached is not None:
            # 命中缓存，直接使用
        else:
            # 未命中，调用 LLM 重新生成

    线程安全：所有读写都加锁，支持后台预规划线程与主线程并发。
    """

    def __init__(self, io_path: str | Path | None = None) -> None:
        """初始化缓存。

        Args:
            io_path: 可选的落盘路径。如果提供，每次写入会同步持久化到该 JSON。
                     如果不提供，纯内存缓存（进程退出即丢失）。
        """
        self._lock = threading.Lock()
        self._plans: dict[int, dict[str, Any]] = {}
        self._pending: set[int] = set()       # 正在后台预规划的章节号
        self._io_path: Path | None = Path(io_path) if io_path else None
        if self._io_path and self._io_path.exists():
            try:
                data = json.loads(self._io_path.read_text(encoding="utf-8"))
                for k, v in (data.get("plans") or {}).items():
                    try:
                        self._plans[int(k)] = v
                    except (TypeError, ValueError):
                        continue
            except Exception:
                # 文件损坏不致命，当作空缓存
                pass

    # ------------------------------------------------------------------ #
    # 基础读写
    # ------------------------------------------------------------------ #
    def get(self, chapter: int) -> dict[str, Any] | None:
        """获取已预规划的 plan；返回 None 表示未命中或正在预规划中。"""
        with self._lock:
            return self._plans.get(int(chapter))

    def put(self, chapter: int, plan: dict[str, Any]) -> None:
        """写入预规划 plan。"""
        ch = int(chapter)
        with self._lock:
            self._plans[ch] = plan
            self._pending.discard(ch)
        self._persist_locked()

    def has(self, chapter: int) -> bool:
        with self._lock:
            return int(chapter) in self._plans

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()
            self._pending.clear()
        self._persist_locked()

    def size(self) -> int:
        with self._lock:
            return len(self._plans)

    def all_chapters(self) -> list[int]:
        with self._lock:
            return sorted(self._plans.keys())

    # ------------------------------------------------------------------ #
    # pending 状态：标记"正在后台预规划"，避免重复触发
    # ------------------------------------------------------------------ #
    def mark_pending(self, chapter: int) -> bool:
        """标记章节为"正在预规划"。

        Returns:
            True  - 成功标记（之前未在 pending 也不在 plans）
            False - 已存在或已在 pending（说明已经触发了）
        """
        ch = int(chapter)
        with self._lock:
            if ch in self._plans or ch in self._pending:
                return False
            self._pending.add(ch)
            return True

    def unmark_pending(self, chapter: int) -> None:
        """取消 pending 标记（预规划失败时调用）。"""
        with self._lock:
            self._pending.discard(int(chapter))

    def is_pending(self, chapter: int) -> bool:
        with self._lock:
            return int(chapter) in self._pending

    # ------------------------------------------------------------------ #
    # 落盘
    # ------------------------------------------------------------------ #
    def _persist_locked(self) -> None:
        if not self._io_path:
            return
        try:
            payload = {
                "plans": {str(k): v for k, v in self._plans.items()},
            }
            self._io_path.parent.mkdir(parents=True, exist_ok=True)
            self._io_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # 落盘失败不致命（in-memory 仍然可用）
            pass


# ============================================================
# LangGraphRuntime 钩子：单例 cache 挂在 runtime 上
# ============================================================
RUNTIME_CACHE_ATTR = "_prefetch_plan_cache"


def get_runtime_cache(runtime: Any) -> PrefetchPlanCache:
    """获取/惰性创建 runtime 上的预规划缓存单例。

    之所以挂在 runtime 上：
    - writer_subgraph 和 architect_subgraph 都要访问
    - runtime 是 LangGraphRuntime 实例，跨节点共享
    - 单例保证后台线程和主线程看到的是同一个缓存

    防御 MagicMock 污染：当 runtime 是 MagicMock 时，第一次 getattr 会返回
    Mock 自身而非 None，会污染后续所有调用。因此增加 isinstance 校验，
    不合法的 cache 一律重建。
    """
    cache = getattr(runtime, RUNTIME_CACHE_ATTR, None)
    if not isinstance(cache, PrefetchPlanCache):
        # 优先从 cfg 读 io_path（如果以后要落盘）；当前默认纯内存
        io_path = None
        try:
            cfg = getattr(runtime, "cfg", None)
            if cfg is not None and hasattr(cfg, "workspace_dir"):
                # workspace_dir 下的 .prefetch_plan.json
                # 注意：必须严格校验为 str/Path，否则 MagicMock 的自动属性会被
                # 当成"目录名"，污染出 `<MagicMock id='...'>` 之类的乱目录。
                wd = getattr(cfg, "workspace_dir", None)
                if isinstance(wd, (str, Path)) and str(wd).strip():
                    io_path = str(Path(wd) / ".prefetch_plan.json")
        except Exception:
            io_path = None
        cache = PrefetchPlanCache(io_path=io_path)
        try:
            setattr(runtime, RUNTIME_CACHE_ATTR, cache)
        except Exception:
            # runtime 不允许 setattr 时退化：直接用局部 cache
            pass
    return cache


def reset_runtime_cache(runtime: Any) -> None:
    """清空 runtime 上的预规划缓存（测试用）。"""
    if hasattr(runtime, RUNTIME_CACHE_ATTR):
        try:
            delattr(runtime, RUNTIME_CACHE_ATTR)
        except Exception:
            pass


# ============================================================
# 后台预规划触发器
# ============================================================
def trigger_prefetch_plan(
    runtime: Any,
    next_chapter: int,
    seed_text: str,
) -> bool:
    """在后台线程触发下一章预规划。

    调用方：writer_subgraph 写完当前章后调用。
    行为：
    1. 检查 next_chapter 是否已存在 / 已在 pending → 跳过
    2. 标记 pending
    3. 后台线程调用 architect.build_dynamic_plan() → plan_chapter 工具 → 缓存
    4. 后台异常时 unmark_pending + 记录日志

    Returns:
        True  - 已成功提交后台任务
        False - 已存在 / 已在 pending / 其它原因未提交
    """
    if next_chapter <= 0:
        return False

    cache = get_runtime_cache(runtime)
    if not cache.mark_pending(next_chapter):
        return False

    worker = _PrefetchWorker(
        runtime=runtime,
        chapter=int(next_chapter),
        seed_text=str(seed_text or ""),
    )
    worker.start()
    return True


class _PrefetchWorker(threading.Thread):
    """后台预规划工作线程。"""

    def __init__(self, runtime: Any, chapter: int, seed_text: str) -> None:
        super().__init__(daemon=True, name=f"prefetch-plan-ch{chapter}")
        self._runtime = runtime
        self._chapter = int(chapter)
        self._seed_text = seed_text

    def run(self) -> None:
        cache = get_runtime_cache(self._runtime)
        chapter = self._chapter
        try:
            architect = self._runtime.get_agent("architect")
            context = self._runtime.runner.call_tool("novel_context", {"chapter": chapter})
            plan_payload = architect.build_dynamic_plan(self._seed_text, chapter, context, "")
            # 持久化到 plan_chapter 工具（确保磁盘也有一份）
            self._runtime.runner.call_tool("plan_chapter", plan_payload)
            # 写入预规划缓存
            cache.put(chapter, plan_payload)
            # 日志：emit_event（如果在）
            emit = getattr(self._runtime, "emit_event", None)
            if callable(emit):
                from datetime import datetime
                from ainovel_py.host.events import Event
                emit(Event(
                    time=datetime.now(),
                    category="AGENT",
                    summary=f"PrefetchPlanCache: ch{chapter} 预规划完成",
                    level="info",
                ))
        except Exception as exc:
            cache.unmark_pending(chapter)
            # 日志
            emit = getattr(self._runtime, "emit_event", None)
            if callable(emit):
                from datetime import datetime
                from ainovel_py.host.events import Event
                emit(Event(
                    time=datetime.now(),
                    category="AGENT",
                    summary=f"PrefetchPlanCache: ch{chapter} 预规划失败: {type(exc).__name__}: {exc}",
                    level="warn",
                ))

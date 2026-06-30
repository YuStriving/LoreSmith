"""优化 ①-3 单元测试：store/io.py per-directory 锁。

验证：
1. 跨目录并发写不阻塞（用 timing 验证）
2. 同目录并发写互斥（数据完整性）
3. 旧的 read_file / with_write_lock 行为不变
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ainovel_py.store.io import IO


def test_per_dir_lock_basic():
    """基础测试：写入/读取不同目录互不干扰。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        io = IO(tmpdir)
        io.write_json("a/x.json", {"a": 1})
        io.write_json("b/x.json", {"b": 2})
        assert io.read_json("a/x.json") == {"a": 1}
        assert io.read_json("b/x.json") == {"b": 2}
        print("[PASS] 1.1 基础读写不同目录")


def test_per_dir_lock_parallel_writes():
    """跨目录并发写不阻塞。"""
    import tempfile
    import ainovel_py.store.io as io_mod
    with tempfile.TemporaryDirectory() as tmpdir:
        io = IO(tmpdir)
        # 模拟延迟以验证锁行为
        delay_per_write = 0.2  # 每次写入延迟 200ms

        def slow_write(self, rel, data):
            time.sleep(delay_per_write)
            Path(self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            Path(self.dir / rel).write_bytes(data)

        # 临时 monkey-patch（不依赖实例绑定）
        original_class_write = io_mod.IO.write_file_unlocked
        io_mod.IO.write_file_unlocked = slow_write
        try:
            # 3 个线程分别写 3 个不同目录
            t_start = time.time()

            def worker(name):
                io.write_json(f"dir_{name}/x.json", {"name": name})

            threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b", "c")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            elapsed = time.time() - t_start
            # 串行需要 3*0.2=0.6s，并行应该 < 0.4s
            assert elapsed < 0.4, f"per-dir lock should allow parallel writes, but took {elapsed:.2f}s"
            print(f"[PASS] 1.2 跨目录并发写不阻塞 (3线程, elapsed={elapsed:.2f}s)")
        finally:
            io_mod.IO.write_file_unlocked = original_class_write


def test_per_dir_lock_same_dir_mutual_exclusion():
    """同目录并发写互斥。"""
    import tempfile
    import ainovel_py.store.io as io_mod
    with tempfile.TemporaryDirectory() as tmpdir:
        io = IO(tmpdir)
        active_count = 0
        max_active = 0
        active_lock = threading.Lock()

        def instrumented_write(self, rel, data):
            nonlocal active_count, max_active
            with active_lock:
                active_count += 1
                max_active = max(max_active, active_count)
            time.sleep(0.05)
            try:
                Path(self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
                Path(self.dir / rel).write_bytes(data)
            finally:
                with active_lock:
                    active_count -= 1

        original_class_write = io_mod.IO.write_file_unlocked
        io_mod.IO.write_file_unlocked = instrumented_write
        try:
            # 5 个线程同时写同一目录
            def worker(i):
                io.write_json(f"shared/file_{i}.json", {"i": i})

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # 同目录下应串行（max_active==1）
            assert max_active == 1, f"same dir should be serialized, got max_active={max_active}"
            print(f"[PASS] 1.3 同目录写互斥 (max_active=1)")
        finally:
            io_mod.IO.write_file_unlocked = original_class_write


def test_legacy_global_lock_unchanged():
    """旧 API 仍使用全局锁。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        io = IO(tmpdir)
        # with_write_lock 使用全局锁 _mu
        result = io.with_write_lock(lambda: "ok")
        assert result == "ok"
        # read_file 仍使用全局锁
        io.write_json("test.json", {"x": 1})
        assert io.read_json("test.json") == {"x": 1}
        print("[PASS] 1.4 旧 API 向后兼容")


if __name__ == "__main__":
    print("=" * 60)
    print("优化 ①-3 单元测试：per-directory 锁")
    print("=" * 60)
    test_per_dir_lock_basic()
    test_per_dir_lock_parallel_writes()
    test_per_dir_lock_same_dir_mutual_exclusion()
    test_legacy_global_lock_unchanged()
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)

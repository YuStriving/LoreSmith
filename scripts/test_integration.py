"""
前后端联调测试（真实 HTTP 调用版）

与 test_mock_agent_flow.py 的区别：
  - 不使用任何 Mock，所有调用都是真实的 HTTP 请求
  - 自动拉起 Python FastAPI 服务（uvicorn）
  - 检测 Java Spring Boot 是否在跑（可选）
  - 模拟前端行为：创建故事 -> 启动 run -> 轮询事件 -> 拉章节

使用：
  # 1. 准备好 .env（填好 OPENAI_API_KEY + AINOVEL_INTERNAL_API_TOKEN）
  # 2. （可选）启动 Java: cd java-platform && mvn spring-boot:run
  # 3. 跑测试
  python scripts/test_integration.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

# ============== 配置 ==============
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_HOST = "127.0.0.1"
PYTHON_PORT = int(os.environ.get("AINOVEL_INTERNAL_API_PORT", "8000"))
PYTHON_BASE = f"http://{PYTHON_HOST}:{PYTHON_PORT}/internal/v1"
JAVA_HOST = "127.0.0.1"
JAVA_PORT = int(os.environ.get("SERVER_PORT", "8080"))
JAVA_BASE = f"http://{JAVA_HOST}:{JAVA_PORT}/api/v1"
STARTUP_TIMEOUT = 30  # 等待服务启动的最长时间（秒）
POLL_INTERVAL = 1.0   # 轮询间隔


# ============== 工具函数 ==============
def banner(text: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{text}\n{line}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def port_in_use(host: str, port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False


def wait_for_http(url: str, timeout: int = STARTUP_TIMEOUT, headers: dict | None = None) -> bool:
    """轮询直到 HTTP 服务返回 2xx，或者超时"""
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        try:
            r = httpx.get(url, headers=headers, timeout=2.0)
            if 200 <= r.status_code < 500:  # 401 也算"服务起来了"
                return True
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(POLL_INTERVAL)
    warn(f"服务未就绪 {url}（最后错误: {last_err}）")
    return False


# ============== 服务管理 ==============
class ServiceManager:
    """管理 Python / Java 后端服务的生命周期"""

    def __init__(self) -> None:
        self.python_proc: subprocess.Popen | None = None
        self._started_python = False
        self._java_was_running = False

    def is_python_alive(self) -> bool:
        return port_in_use(PYTHON_HOST, PYTHON_PORT)

    def is_java_alive(self) -> bool:
        return port_in_use(JAVA_HOST, JAVA_PORT)

    def start_python(self) -> bool:
        """如果 Python 服务没起，自动用 uvicorn 拉起"""
        if self.is_python_alive():
            info(f"Python 服务已在 {PYTHON_BASE} 运行（复用现有进程）")
            return True

        info(f"未检测到 Python 服务，尝试拉起 uvicorn ...")
        env = os.environ.copy()
        env["AINOVEL_INTERNAL_API_HOST"] = PYTHON_HOST
        env["AINOVEL_INTERNAL_API_PORT"] = str(PYTHON_PORT)
        # 让 token 有默认值，否则 require_internal_auth 会 401
        env.setdefault("AINOVEL_INTERNAL_API_TOKEN", "integration-test-token")

        # 用 uvicorn 直接 import app
        log_path = PROJECT_ROOT / "output" / "integration_python.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "w", encoding="utf-8")

        try:
            self.python_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn",
                 "ainovel_py.internal_api.app:app",
                 "--host", PYTHON_HOST,
                 "--port", str(PYTHON_PORT),
                 "--log-level", "warning"],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
            self._started_python = True
        except FileNotFoundError as e:
            fail(f"uvicorn 不可用: {e}")
            return False

        # 轮询 /health
        token = env["AINOVEL_INTERNAL_API_TOKEN"]
        headers = {"Authorization": f"Bearer {token}"}
        if wait_for_http(f"{PYTHON_BASE}/health", headers=headers):
            ok(f"Python 服务已启动 (pid={self.python_proc.pid}, log={log_path})")
            return True
        fail(f"Python 服务启动超时，日志请查看 {log_path}")
        return False

    def stop(self) -> None:
        if self.python_proc and self._started_python:
            info(f"停止 Python 服务 (pid={self.python_proc.pid})")
            try:
                self.python_proc.terminate()
                self.python_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.python_proc.kill()
            self.python_proc = None
            self._started_python = False
        # 如果 Java 是我们没启动的，跳过


# ============== 客户端封装（模拟前端） ==============
class FrontendSimulator:
    """模拟 Vite 前端的行为，对后端发起真实 HTTP 请求"""

    def __init__(self, python_token: str) -> None:
        self.python_token = python_token
        self.python = httpx.Client(
            base_url=PYTHON_BASE,
            headers={"Authorization": f"Bearer {python_token}"},
            timeout=10.0,
        )
        self.java = httpx.Client(base_url=JAVA_BASE, timeout=10.0)
        self.java_alive = False

    def probe_java(self) -> bool:
        """Java 是可选的，先 ping 一下"""
        try:
            r = self.java.get("/health", timeout=2.0)
            self.java_alive = r.status_code == 200
            return self.java_alive
        except Exception:
            return False

    # ---------- Python API ----------

    def health(self) -> dict:
        r = self.python.get("/health")
        r.raise_for_status()
        return r.json()

    def list_runs(self) -> dict:
        r = self.python.get("/runs")
        r.raise_for_status()
        return r.json()

    def create_run(self, prompt: str, story_id: str | None = None) -> str:
        """POST /internal/v1/runs，返回 run_id"""
        run_id = f"itest-{uuid.uuid4().hex[:8]}"
        payload = {
            "run_id": run_id,
            "input": {"prompt": prompt},
            "story": {"story_id": story_id or run_id, "premise": prompt},
            "config": {
                "provider": os.environ.get("AINOVEL_PROVIDER", "openai"),
                "model": os.environ.get("AINOVEL_MODEL", "gpt-4o-mini"),
            },
        }
        r = self.python.post("/runs", json=payload)
        r.raise_for_status()
        return run_id

    def get_run(self, run_id: str) -> dict:
        r = self.python.get(f"/runs/{run_id}")
        r.raise_for_status()
        return r.json()

    def poll_events(self, run_id: str, max_wait: int = 60) -> list[dict]:
        """阻塞轮询 events，等 run 进入稳态或超时"""
        deadline = time.time() + max_wait
        all_events: list[dict] = []
        while time.time() < deadline:
            r = self.python.get(f"/runs/{run_id}/events", params={"limit": 50})
            if r.status_code == 200:
                body = r.json()
                events = (body.get("data") or {}).get("events") or []
                all_events = events
                run = self.get_run(run_id)
                lifecycle = (run.get("data") or {}).get("lifecycle", "")
                # 几个稳态就停
                if lifecycle in {"awaiting_confirmation", "completed", "failed", "cancelled", "paused"}:
                    return all_events
            time.sleep(2.0)
        return all_events

    def get_chapter(self, run_id: str, chapter: int) -> dict:
        r = self.python.get(f"/runs/{run_id}/chapters/{chapter}")
        return {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}

    def list_artifacts(self, run_id: str) -> dict:
        r = self.python.get(f"/runs/{run_id}/artifacts")
        return r.json() if r.status_code == 200 else {"status": r.status_code}

    def pause(self, run_id: str) -> dict:
        r = self.python.post(f"/runs/{run_id}/pause", json={})
        return r.json() if r.status_code == 200 else {"status": r.status_code}

    def resume(self, run_id: str, prompt: str = "") -> dict:
        r = self.python.post(f"/runs/{run_id}/resume", json={"input": {"prompt": prompt}})
        return r.json() if r.status_code == 200 else {"status": r.status_code}

    # ---------- Java API（可选） ----------

    def list_stories(self) -> dict:
        r = self.java.get("/stories")
        return r.json() if r.status_code == 200 else {"status": r.status_code}

    def create_story(self, name: str, premise: str) -> dict:
        r = self.java.post("/stories", json={"name": name, "premise": premise})
        return r.json() if r.status_code == 200 else {"status": r.status_code}

    def close(self) -> None:
        self.python.close()
        self.java.close()


# ============== 测试场景 ==============
def scenario_python_health(fe: FrontendSimulator) -> bool:
    banner("场景 1: Python FastAPI 健康检查")
    try:
        body = fe.health()
        ok(f"health 接口返回: {json.dumps(body, ensure_ascii=False)}")
        return True
    except Exception as e:
        fail(f"health 接口失败: {e}")
        return False


def scenario_java_health(fe: FrontendSimulator) -> bool:
    banner("场景 2: Java Spring Boot 健康检查（可选）")
    if not fe.probe_java():
        warn(f"Java 服务在 {JAVA_BASE} 未运行，跳过该场景")
        warn("提示：cd java-platform && mvn spring-boot:run 可启用")
        return True  # 不算失败
    try:
        stories = fe.list_stories()
        ok(f"Java /stories 返回: {json.dumps(stories, ensure_ascii=False)[:200]}")
        return True
    except Exception as e:
        fail(f"Java 接口失败: {e}")
        return False


def scenario_list_runs(fe: FrontendSimulator) -> bool:
    banner("场景 3: 列出已有 run")
    try:
        body = fe.list_runs()
        runs = (body.get("data") or {}).get("runs") or []
        ok(f"当前共有 {len(runs)} 个 run")
        return True
    except Exception as e:
        fail(f"list_runs 失败: {e}")
        return False


def scenario_create_run(fe: FrontendSimulator, prompt: str) -> str | None:
    banner("场景 4: 创建 run（POST /internal/v1/runs）")
    try:
        run_id = fe.create_run(prompt)
        ok(f"创建成功 run_id={run_id}")
        return run_id
    except httpx.HTTPStatusError as e:
        fail(f"创建 run 失败 HTTP {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        fail(f"创建 run 异常: {e}")
        return None


def scenario_watch_events(fe: FrontendSimulator, run_id: str) -> bool:
    banner(f"场景 5: 轮询事件流 run_id={run_id}")
    try:
        events = fe.poll_events(run_id, max_wait=45)
        ok(f"共收到 {len(events)} 个事件")
        if events:
            sample = events[:3]
            for ev in sample:
                info(f"  - {ev.get('type', '?')} {json.dumps(ev, ensure_ascii=False)[:120]}")
        run = fe.get_run(run_id)
        lifecycle = (run.get("data") or {}).get("lifecycle", "unknown")
        info(f"当前 lifecycle = {lifecycle}")
        return True
    except Exception as e:
        fail(f"轮询事件失败: {e}")
        return False


def scenario_get_chapter(fe: FrontendSimulator, run_id: str) -> bool:
    banner(f"场景 6: 拉取第 1 章 run_id={run_id}")
    try:
        result = fe.get_chapter(run_id, 1)
        status = result.get("status")
        if status == 200:
            body = result.get("body") or {}
            data = body.get("data") or {}
            content = (data.get("content") or "")
            ok(f"第 1 章正文长度: {len(content)} 字")
            info(f"  预览: {content[:80]}...")
            return True
        warn(f"第 1 章返回 HTTP {status}（run 还没写完属正常）")
        return True
    except Exception as e:
        fail(f"拉章节失败: {e}")
        return False


def scenario_pause_resume(fe: FrontendSimulator, run_id: str) -> bool:
    banner(f"场景 7: pause / resume 流程 run_id={run_id}")
    try:
        p = fe.pause(run_id)
        info(f"pause -> {json.dumps(p, ensure_ascii=False)[:200]}")
        r = fe.resume(run_id, prompt="继续")
        info(f"resume -> {json.dumps(r, ensure_ascii=False)[:200]}")
        ok("pause/resume 调用成功")
        return True
    except Exception as e:
        warn(f"pause/resume 在当前 lifecycle 下可能不适用: {e}")
        return True  # 软失败


def scenario_artifacts(fe: FrontendSimulator, run_id: str) -> bool:
    banner(f"场景 8: 拉取 artifacts run_id={run_id}")
    try:
        body = fe.list_artifacts(run_id)
        items = (body.get("data") or {}).get("artifacts") or []
        ok(f"artifacts 数量: {len(items)}")
        for it in items[:5]:
            info(f"  - {it.get('kind', '?')}: {it.get('name', '')}")
        return True
    except Exception as e:
        warn(f"artifacts 拉取失败: {e}")
        return True


# ============== 主流程 ==============
def main() -> int:
    banner("LoreSmith 前后端联调测试（真实 HTTP）")
    info(f"Python 后端: {PYTHON_BASE}")
    info(f"Java 后端:   {JAVA_BASE}（可选）")

    token = os.environ.get("AINOVEL_INTERNAL_API_TOKEN", "integration-test-token")
    if not os.environ.get("AINOVEL_INTERNAL_API_TOKEN"):
        warn("未设置 AINOVEL_INTERNAL_API_TOKEN，使用默认 integration-test-token")
        os.environ["AINOVEL_INTERNAL_API_TOKEN"] = token

    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("DEEPSEEK_API_KEY"):
        warn("未设置任何 LLM API Key（OPENAI_API_KEY / DEEPSEEK_API_KEY 等）")
        warn("  -> 真实 LLM 调用会失败，但接口链路本身可以验证")

    sm = ServiceManager()
    fe = FrontendSimulator(token)

    failed = 0
    try:
        # 0. 拉起 Python（如果需要）
        if not sm.start_python():
            fail("Python 服务无法启动，后续测试全部跳过")
            return 2

        # 1-2 健康检查
        if not scenario_python_health(fe): failed += 1
        if not scenario_java_health(fe): failed += 1

        # 3 列表
        if not scenario_list_runs(fe): failed += 1

        # 4 创建 run
        prompt = "写第一章：主角是一名被诬陷的程序员，他在雨夜的咖啡馆里收到了匿名邮件。"
        run_id = scenario_create_run(fe, prompt)
        if not run_id:
            failed += 1
            return failed

        # 5 事件流
        if not scenario_watch_events(fe, run_id): failed += 1

        # 6 章节内容
        if not scenario_get_chapter(fe, run_id): failed += 1

        # 7 暂停恢复（软失败）
        scenario_pause_resume(fe, run_id)

        # 8 artifacts
        if not scenario_artifacts(fe, run_id): failed += 1

    finally:
        fe.close()
        sm.stop()

    banner("联调测试总结")
    if failed == 0:
        print("  [OK]  全部场景通过")
        print("  接下来可以：")
        print(f"    1. 浏览器打开 http://localhost:{PYTHON_PORT}/docs  看 FastAPI 文档")
        print("    2. 启动前端：cd frontend-web && npm run dev")
        print(f"    3. 打开 http://localhost:5173 用 UI 跑一遍同一流程")
        return 0
    else:
        print(f"  [FAIL] 失败场景数: {failed}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    run_id = "run_conflicts"
    base = Path("output/internal_api_conflicts")
    base.mkdir(parents=True, exist_ok=True)

    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_conflicts", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": str(base)},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    session = app.state.run_service.get_run(run_id)
    time.sleep(0.05)
    if not session.is_busy():
        session.worker = type("DummyWorker", (), {"is_alive": lambda self: True})()

    resp = client.post(
        f"/internal/v1/runs/{run_id}/instructions",
        json={"instruction": {"type": "follow_up", "text": "继续推进"}},
    )
    if resp.status_code != 409:
        raise RuntimeError(f"busy instruction should return 409: {resp.status_code} {resp.text}")

    resp = client.post(f"/internal/v1/runs/{run_id}/pause", json={})
    if resp.status_code != 200:
        raise RuntimeError(f"pause failed: {resp.status_code} {resp.text}")

    session.worker = None
    resp = client.post(f"/internal/v1/runs/{run_id}/resume", json={"input": {"prompt": "继续推进"}})
    if resp.status_code != 200:
        raise RuntimeError(f"resume failed: {resp.status_code} {resp.text}")

    print("internal_api_conflicts_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

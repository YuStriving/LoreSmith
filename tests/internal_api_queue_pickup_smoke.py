from __future__ import annotations

import time

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    run_id = "run_queue_pickup"
    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_queue_pickup", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": "output/internal_api_queue_pickup"},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    seen = set()
    for _ in range(20):
        resp = client.get(f"/internal/v1/runs/{run_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"get run failed: {resp.status_code} {resp.text}")
        seen.add(resp.json()["data"]["status"])
        time.sleep(0.05)

    if "queued" not in seen and "running" not in seen and "waiting_input" not in seen:
        raise RuntimeError(f"worker pickup states missing: {seen}")

    print("internal_api_queue_pickup_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

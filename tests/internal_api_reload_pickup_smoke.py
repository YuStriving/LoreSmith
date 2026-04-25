from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    registry_path = Path("output/internal_api/reload_pickup_runs.json")
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["AINOVEL_INTERNAL_API_REGISTRY"] = str(registry_path)

    run_id = "run_reload_pickup"
    app1 = create_app()
    client1 = TestClient(app1)
    resp = client1.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_reload_pickup", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": "output/internal_api_reload_pickup"},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    app2 = create_app()
    client2 = TestClient(app2)
    seen = set()
    for _ in range(20):
        resp = client2.get(f"/internal/v1/runs/{run_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"reloaded get run failed: {resp.status_code} {resp.text}")
        seen.add(resp.json()["data"]["status"])
        time.sleep(0.05)

    if not ({"queued", "running", "waiting_input"} & seen):
        raise RuntimeError(f"reload pickup states missing: {seen}")

    print("internal_api_reload_pickup_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

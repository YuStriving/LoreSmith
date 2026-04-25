from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    os.environ["AINOVEL_INTERNAL_API_REGISTRY"] = "output/internal_api/cancel_registry.json"
    app = create_app()
    client = TestClient(app)

    run_id = "run_cancel"
    base = Path("output/internal_api_cancel")
    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_cancel", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": str(base)},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    resp = client.post(f"/internal/v1/runs/{run_id}/cancel")
    if resp.status_code != 200:
        raise RuntimeError(f"cancel failed: {resp.status_code} {resp.text}")
    if resp.json()["data"]["status"] != "canceled":
        raise RuntimeError(f"cancel status mismatch: {resp.text}")

    resp = client.get(f"/internal/v1/runs/{run_id}")
    if resp.status_code != 200 or resp.json()["data"]["status"] != "canceled":
        raise RuntimeError(f"persisted canceled state mismatch: {resp.text}")

    print("internal_api_cancel_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

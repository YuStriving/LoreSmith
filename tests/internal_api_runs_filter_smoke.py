from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    os.environ["AINOVEL_INTERNAL_API_REGISTRY"] = "output/internal_api/runs_filter_registry.json"
    app = create_app()
    client = TestClient(app)

    base1 = Path("output/internal_api_runs_filter_1")
    base2 = Path("output/internal_api_runs_filter_2")
    client.post(
        "/internal/v1/runs",
        json={
            "run_id": "run_filter_running",
            "story": {"story_id": "story_filter_running", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": str(base1)},
        },
    )
    client.post(
        "/internal/v1/runs",
        json={
            "run_id": "run_filter_canceled",
            "story": {"story_id": "story_filter_canceled", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": str(base2)},
        },
    )
    client.post("/internal/v1/runs/run_filter_canceled/cancel")

    resp = client.get("/internal/v1/runs?status=canceled")
    if resp.status_code != 200:
        raise RuntimeError(f"filtered runs failed: {resp.status_code} {resp.text}")
    items = resp.json()["data"]["items"]
    run_ids = {item["run_id"] for item in items}
    if "run_filter_canceled" not in run_ids:
        raise RuntimeError(f"canceled run missing: {run_ids}")
    if "run_filter_running" in run_ids:
        raise RuntimeError(f"running run leaked into canceled filter: {run_ids}")

    print("internal_api_runs_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

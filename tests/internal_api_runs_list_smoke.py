from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    for idx in (1, 2):
        run_id = f"run_list_{idx}"
        base = Path(f"output/internal_api_list_{idx}")
        resp = client.post(
            "/internal/v1/runs",
            json={
                "run_id": run_id,
                "story": {"story_id": f"story_list_{idx}", "style": "default"},
                "execution": {"provider": "openai", "model": "gpt-4o-mini"},
                "input": {"mode": "start", "prompt": "写一个测试故事。"},
                "storage": {"base_path": str(base)},
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    resp = client.get("/internal/v1/runs")
    if resp.status_code != 200:
        raise RuntimeError(f"list runs failed: {resp.status_code} {resp.text}")
    items = resp.json()["data"]["items"]
    run_ids = {item["run_id"] for item in items}
    if "run_list_1" not in run_ids or "run_list_2" not in run_ids:
        raise RuntimeError(f"runs missing from list: {run_ids}")

    print("internal_api_runs_list_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

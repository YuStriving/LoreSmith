from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    pairs = [("run_story_a", "story_a", "output/internal_api_story_a"), ("run_story_b", "story_b", "output/internal_api_story_b")]
    for run_id, story_id, base in pairs:
        resp = client.post(
            "/internal/v1/runs",
            json={
                "run_id": run_id,
                "story": {"story_id": story_id, "style": "default"},
                "execution": {"provider": "openai", "model": "gpt-4o-mini"},
                "input": {"mode": "start", "prompt": "写一个测试故事。"},
                "storage": {"base_path": base},
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    resp = client.get("/internal/v1/runs?story_id=story_b")
    if resp.status_code != 200:
        raise RuntimeError(f"story filter failed: {resp.status_code} {resp.text}")
    items = resp.json()["data"]["items"]
    run_ids = {item["run_id"] for item in items}
    if run_ids != {"run_story_b"}:
        raise RuntimeError(f"story filter mismatch: {run_ids}")

    print("internal_api_runs_story_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    registry_path = Path("output/internal_api/reload_runs.json")
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["AINOVEL_INTERNAL_API_REGISTRY"] = str(registry_path)

    base = Path("output/internal_api_reload")
    (base / "chapters").mkdir(parents=True, exist_ok=True)
    (base / "chapters" / "01.md").write_text("# 第1章\n\n重载正文", encoding="utf-8")
    (base / "meta").mkdir(parents=True, exist_ok=True)
    (base / "meta" / "progress.json").write_text('{"phase":"writing","current_chapter":2,"completed_chapters":[1],"total_word_count":4,"chapter_word_counts":{"1":4}}', encoding="utf-8")

    app1 = create_app()
    client1 = TestClient(app1)
    run_id = "run_reload"
    resp = client1.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_reload", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": str(base)},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    app2 = create_app()
    client2 = TestClient(app2)

    resp = client2.get(f"/internal/v1/runs/{run_id}")
    if resp.status_code != 200:
        raise RuntimeError(f"reloaded get run failed: {resp.status_code} {resp.text}")

    resp = client2.get(f"/internal/v1/runs/{run_id}/chapters/1")
    if resp.status_code != 200:
        raise RuntimeError(f"reloaded get chapter failed: {resp.status_code} {resp.text}")
    if "重载正文" not in resp.json()["data"]["chapter"]["content"]:
        raise RuntimeError("reloaded chapter content mismatch")

    print("internal_api_reload_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

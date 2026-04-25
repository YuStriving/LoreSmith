from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    run_id = "run_smoke"
    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_smoke", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": "output/internal_api_smoke"},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")
    data = resp.json()["data"]
    if data["run_id"] != run_id:
        raise RuntimeError("run_id mismatch")

    resp = client.get(f"/internal/v1/runs/{run_id}")
    if resp.status_code != 200:
        raise RuntimeError(f"get run failed: {resp.status_code} {resp.text}")
    run = resp.json()["data"]
    if run["run_id"] != run_id:
        raise RuntimeError("get run returned wrong run_id")

    base = Path("output/internal_api_smoke")
    base.mkdir(parents=True, exist_ok=True)
    (base / "chapters").mkdir(parents=True, exist_ok=True)
    (base / "chapters" / "01.md").write_text("# 第1章\n\n测试正文", encoding="utf-8")
    (base / "summaries").mkdir(parents=True, exist_ok=True)
    (base / "summaries" / "01.json").write_text('{"chapter":1,"summary":"测试摘要","characters":[],"key_events":[]}', encoding="utf-8")
    (base / "reviews").mkdir(parents=True, exist_ok=True)
    (base / "reviews" / "01.json").write_text('{"chapter":1,"scope":"chapter","issues":[],"verdict":"pass","summary":"测试评审"}', encoding="utf-8")

    resp = client.get(f"/internal/v1/runs/{run_id}/chapters/1")
    if resp.status_code != 200:
        raise RuntimeError(f"get chapter failed: {resp.status_code} {resp.text}")
    chapter = resp.json()["data"]["chapter"]
    if "测试正文" not in chapter["content"]:
        raise RuntimeError("chapter content missing")
    if chapter["summary"]["text"] != "测试摘要":
        raise RuntimeError("chapter summary mismatch")
    if chapter["review"]["verdict"] != "pass":
        raise RuntimeError("chapter review mismatch")

    resp = client.get("/internal/v1/runs/missing")
    if resp.status_code != 404:
        raise RuntimeError("missing run should return 404")

    print("internal_api_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

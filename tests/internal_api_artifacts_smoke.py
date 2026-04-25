from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    run_id = "run_artifacts"
    base = Path("output/internal_api_artifacts")
    (base / "chapters").mkdir(parents=True, exist_ok=True)
    (base / "chapters" / "01.md").write_text("# 第1章\n\n测试正文", encoding="utf-8")
    (base / "summaries").mkdir(parents=True, exist_ok=True)
    (base / "summaries" / "01.json").write_text('{"chapter":1,"summary":"测试摘要","characters":[],"key_events":[]}', encoding="utf-8")
    (base / "reviews").mkdir(parents=True, exist_ok=True)
    (base / "reviews" / "01.json").write_text('{"chapter":1,"scope":"chapter","issues":[],"verdict":"pass","summary":"测试评审"}', encoding="utf-8")
    (base / "meta").mkdir(parents=True, exist_ok=True)
    (base / "meta" / "progress.json").write_text('{"phase":"writing","current_chapter":2,"completed_chapters":[1],"total_word_count":4,"chapter_word_counts":{"1":4}}', encoding="utf-8")

    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_artifacts", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": str(base)},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    resp = client.get(f"/internal/v1/runs/{run_id}/artifacts")
    if resp.status_code != 200:
        raise RuntimeError(f"get artifacts failed: {resp.status_code} {resp.text}")
    items = resp.json()["data"]["items"]
    types = {item["type"] for item in items}
    if "chapter" not in types or "summary" not in types or "review" not in types:
        raise RuntimeError(f"artifact types missing: {types}")

    print("internal_api_artifacts_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

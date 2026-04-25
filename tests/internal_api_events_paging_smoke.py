from __future__ import annotations

from fastapi.testclient import TestClient

from ainovel_py.host.events import Event
from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    run_id = "run_events_paging"
    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_events_paging", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": "output/internal_api_events_paging"},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    session = app.state.run_service.get_run(run_id)
    session.host._emit_event(Event(summary="事件1", category="SYSTEM", level="info"))
    session.host._emit_event(Event(summary="事件2", category="SYSTEM", level="info"))
    session.host._emit_stream_chunk("content", "流1")

    resp = client.get(f"/internal/v1/runs/{run_id}/events?after_seq=0&limit=2")
    if resp.status_code != 200:
        raise RuntimeError(f"events paging failed: {resp.status_code} {resp.text}")
    data = resp.json()["data"]
    if data["returned_count"] != 2:
        raise RuntimeError(f"returned_count mismatch: {data}")
    if data["total_available"] < 2:
        raise RuntimeError(f"total_available mismatch: {data}")
    if data["next_after_seq"] <= 0:
        raise RuntimeError(f"next_after_seq mismatch: {data}")

    print("internal_api_events_paging_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

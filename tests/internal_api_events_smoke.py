from __future__ import annotations

from fastapi.testclient import TestClient

from ainovel_py.host.events import Event
from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    run_id = "run_events"
    resp = client.post(
        "/internal/v1/runs",
        json={
            "run_id": run_id,
            "story": {"story_id": "story_events", "style": "default"},
            "execution": {"provider": "openai", "model": "gpt-4o-mini"},
            "input": {"mode": "start", "prompt": "写一个测试故事。"},
            "storage": {"base_path": "output/internal_api_events"},
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"create run failed: {resp.status_code} {resp.text}")

    session = app.state.run_service.get_run(run_id)
    session.host._emit_event(Event(summary="测试事件", category="SYSTEM", level="info"))
    session.host._emit_stream_chunk("content", "测试流")

    resp = client.get(f"/internal/v1/runs/{run_id}/events?after_seq=0&limit=20")
    if resp.status_code != 200:
        raise RuntimeError(f"get events failed: {resp.status_code} {resp.text}")
    items = resp.json()["data"]["items"]
    kinds = {item["type"] for item in items}
    if "ui.event" not in kinds:
        raise RuntimeError("ui.event missing")
    if "stream.chunk" not in kinds:
        raise RuntimeError("stream.chunk missing")

    print("internal_api_events_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

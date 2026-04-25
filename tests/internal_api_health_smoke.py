from __future__ import annotations

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)

    resp = client.get("/internal/v1/health")
    if resp.status_code != 200:
        raise RuntimeError(f"health failed: {resp.status_code} {resp.text}")
    data = resp.json()["data"]
    if data["status"] != "ok":
        raise RuntimeError(f"health status mismatch: {resp.text}")
    if "run_count" not in data:
        raise RuntimeError(f"health missing run_count: {resp.text}")

    print("internal_api_health_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from ainovel_py.internal_api.app import create_app


def main() -> int:
    os.environ["AINOVEL_INTERNAL_API_TOKEN"] = "secret-token"
    app = create_app()
    client = TestClient(app)

    resp = client.get("/internal/v1/runs")
    if resp.status_code != 401:
        raise RuntimeError(f"missing token should be 401: {resp.status_code} {resp.text}")

    resp = client.get("/internal/v1/runs", headers={"Authorization": "Bearer wrong"})
    if resp.status_code != 401:
        raise RuntimeError(f"wrong token should be 401: {resp.status_code} {resp.text}")

    resp = client.get("/internal/v1/runs", headers={"Authorization": "Bearer secret-token"})
    if resp.status_code != 200:
        raise RuntimeError(f"correct token should be 200: {resp.status_code} {resp.text}")

    print("internal_api_auth_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

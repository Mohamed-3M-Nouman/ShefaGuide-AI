from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


def test_supervisor_endpoints_enforce_x_supervisor_key(monkeypatch):
    monkeypatch.setattr(settings, "SUPERVISOR_API_KEY", "top-secret-supervisor-key")
    monkeypatch.setenv("SKIP_QDRANT_AUTO_INGEST", "1")
    app = create_app()
    app.state.db_engine = None

    with TestClient(app, headers={}) as client:
        assert client.get("/api/v1/escalations").status_code == 401
        assert client.get("/api/v1/audit-logs").status_code == 401
        assert (
            client.patch(
                "/api/v1/escalations/00000000-0000-0000-0000-000000000000",
                json={"status": "acknowledged"},
            ).status_code
            == 401
        )
        assert (
            client.get("/api/v1/escalations", headers={"X-Supervisor-Key": "wrong-key"}).status_code
            == 401
        )

        ok_esc = client.get(
            "/api/v1/escalations", headers={"X-Supervisor-Key": "top-secret-supervisor-key"}
        )
        assert ok_esc.status_code == 200
        assert ok_esc.json() == {"items": [], "count": 0}

        ok_audit = client.get(
            "/api/v1/audit-logs", headers={"X-Supervisor-Key": "top-secret-supervisor-key"}
        )
        assert ok_audit.status_code == 200

        ok_sse = client.get(
            "/api/v1/escalations/stream",
            params={
                "once": "true",
                "replay_recent": "false",
                "supervisor_key": "top-secret-supervisor-key",
            },
        )
        assert ok_sse.status_code == 200

"""Comprehensive tests for Step 5 Internal Supervisor Dashboard & Audit API Endpoints.

Verifies:
1. Normal clinical symptom with sensitive PII (phone number 01012345678 and name)
   persists to GET /api/v1/audit-logs with 0% PHI leakage.
2. Emergency red-flag symptom ("حاسس بطابوقة على صدري ومسمعة في دراعي الشمال")
   automatically creates a "pending" alert in GET /api/v1/escalations.
3. PATCH /api/v1/escalations/{escalation_id} transitions status from "pending" -> "acknowledged" -> "resolved".
4. Filtering GET /api/v1/escalations?status=pending and GET /api/v1/audit-logs?escalated_only=true works accurately.
5. Root alias routes (/escalations, /escalations/{id}, /audit-logs) match API v1 endpoints.
6. Fail-safe SLO-07 behavior when audit database is unavailable.
7. Validation and 404 handling on invalid or non-existent escalation IDs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limiter import rate_limiter
from app.db.crud import create_engine
from app.db.models import Base
from app.main import app
from app.safety.pii_scrubber import contains_pii


@pytest.fixture
def db_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """TestClient backed by an isolated temporary SQLite database for zero-PHI audit tests."""
    db_file = tmp_path / "step5_audit.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_engine(url)

    # Initialize tables
    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    with asyncio.Runner() as runner:
        runner.run(_setup())

    # Attach engine and enable synchronous audit persistence for tests
    app.state.db_engine = engine
    app.state.sync_audit = True
    rate_limiter.reset()

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    rate_limiter.reset()
    app.state.db_engine = None

    async def _teardown() -> None:
        await engine.dispose()

    with asyncio.Runner() as runner:
        runner.run(_teardown())


# ===========================================================================
# 1. Normal clinical symptom -> Audit Log persistence & 0% PHI leakage
# ===========================================================================


def test_normal_clinical_symptom_audit_log_zero_phi_leakage(db_client: TestClient) -> None:
    """Posting a normal clinical symptom creates a scrubbed entry in /api/v1/audit-logs with 0% PHI."""
    sensitive_phone = "01012345678"
    sensitive_name = "طارق عبد الرحمن"
    user_input = (
        f"أنا اسمي {sensitive_name} ورقم موبايلي {sensitive_phone}، "
        "عندي حرقان ونار قايدة في فم المعدة بقالها تلات أيام بعد الأكل."
    )

    triage_payload = {
        "session_id": "sess_normal_001",
        "user_input": user_input,
    }

    post_resp = db_client.post("/api/v1/triage", json=triage_payload)
    assert post_resp.status_code == 200, post_resp.text
    triage_data = post_resp.json()
    assert triage_data["urgency_level"] in (1, 2, 3)

    # Fetch audit logs
    audit_resp = db_client.get("/api/v1/audit-logs")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()

    assert audit_data["total_count"] >= 1
    assert len(audit_data["items"]) >= 1

    entry = next((i for i in audit_data["items"] if i["session_id"] == "sess_normal_001"), None)
    assert entry is not None, f"Audit log for session not found in: {audit_data}"

    # Verify 0% PHI leakage
    scrubbed = entry["scrubbed_input"]
    assert sensitive_phone not in scrubbed, "Phone number leaked in audit log!"
    assert sensitive_name not in scrubbed, "Patient name leaked in audit log!"
    assert "[REDACTED]" in scrubbed
    assert not contains_pii(scrubbed), f"contains_pii returned true on: {scrubbed}"

    # Verify non-emergency did not enqueue an escalation
    assert entry["escalation_triggered"] is False
    assert entry["symptom_category"] == "gastrointestinal"
    assert entry["latency_ms"] is not None and entry["latency_ms"] >= 0

    # Ensure no escalation was created
    esc_resp = db_client.get("/api/v1/escalations")
    assert esc_resp.status_code == 200
    assert esc_resp.json()["count"] == 0


# ===========================================================================
# 2. Emergency red-flag symptom -> Automatic pending alert in Escalations
# ===========================================================================


def test_red_flag_emergency_symptom_triggers_pending_escalation(db_client: TestClient) -> None:
    """Posting red-flag emergency symptom automatically creates a pending alert in /api/v1/escalations."""
    emergency_input = (
        "أنا اسمي محمود حسن ورقمي 01123456789، "
        "حاسس بطابوقة على صدري ومسمعة في دراعي الشمال ومش قادر أتنفس."
    )

    triage_payload = {
        "session_id": "sess_emergency_cardio_01",
        "user_input": emergency_input,
    }

    triage_resp = db_client.post("/api/v1/triage", json=triage_payload)
    assert triage_resp.status_code == 200, triage_resp.text
    triage_data = triage_resp.json()
    assert triage_data["urgency_level"] == 4
    assert triage_data["escalation_triggered"] is True

    # Check escalations list
    esc_resp = db_client.get("/api/v1/escalations")
    assert esc_resp.status_code == 200
    esc_data = esc_resp.json()
    assert esc_data["count"] == 1
    assert len(esc_data["items"]) == 1

    alert = esc_data["items"][0]
    assert alert["session_id"] == "sess_emergency_cardio_01"
    assert alert["status"] == "pending"
    assert alert["acknowledged_at"] is None
    assert alert["resolved_at"] is None
    assert alert["symptom_category"] == "cardiopulmonary"

    # Verify zero-PHI in escalation alert
    assert "01123456789" not in (alert["scrubbed_summary"] or "")
    assert "محمود حسن" not in (alert["scrubbed_summary"] or "")
    assert not contains_pii(alert["scrubbed_summary"] or "")

    # Check audit log also reflects escalated status
    audit_resp = db_client.get("/api/v1/audit-logs")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert audit_data["escalated_count"] == 1


# ===========================================================================
# 3. PATCH /api/v1/escalations/{escalation_id} lifecycle
# ===========================================================================


def test_escalation_status_lifecycle_transitions(db_client: TestClient) -> None:
    """PATCH /api/v1/escalations/{escalation_id} transitions pending -> acknowledged -> resolved."""
    # 1. Trigger an emergency escalation
    triage_resp = db_client.post(
        "/api/v1/triage",
        json={
            "session_id": "sess_escalation_lifecycle",
            "user_input": "العيان فجأة وشه اتعوج ولسانه تقل ومش قادر ينطق ورجله الشمال وقفت تماماً",
        },
    )
    assert triage_resp.status_code == 200
    assert triage_resp.json()["urgency_level"] == 4

    # 2. Retrieve alert ID
    esc_resp = db_client.get("/api/v1/escalations")
    assert esc_resp.status_code == 200
    items = esc_resp.json()["items"]
    assert len(items) == 1
    alert_id = items[0]["id"]
    assert items[0]["status"] == "pending"

    # 3. Transition to 'acknowledged'
    ack_resp = db_client.patch(
        f"/api/v1/escalations/{alert_id}",
        json={"status": "acknowledged"},
    )
    assert ack_resp.status_code == 200, ack_resp.text
    ack_data = ack_resp.json()
    assert ack_data["id"] == alert_id
    assert ack_data["status"] == "acknowledged"
    assert ack_data["acknowledged_at"] is not None
    assert ack_data["resolved_at"] is None

    # Verify state in GET /api/v1/escalations
    ack_list = db_client.get("/api/v1/escalations?status=acknowledged")
    assert ack_list.status_code == 200
    assert ack_list.json()["count"] == 1
    assert ack_list.json()["items"][0]["status"] == "acknowledged"

    # Pending list should now be empty
    pending_list = db_client.get("/api/v1/escalations?status=pending")
    assert pending_list.status_code == 200
    assert pending_list.json()["count"] == 0

    # 4. Transition to 'resolved'
    res_resp = db_client.patch(
        f"/api/v1/escalations/{alert_id}",
        json={"status": "resolved"},
    )
    assert res_resp.status_code == 200, res_resp.text
    res_data = res_resp.json()
    assert res_data["id"] == alert_id
    assert res_data["status"] == "resolved"
    assert res_data["acknowledged_at"] is not None
    assert res_data["resolved_at"] is not None

    # Verify state in GET /api/v1/escalations
    resolved_list = db_client.get("/api/v1/escalations?status=resolved")
    assert resolved_list.status_code == 200
    assert resolved_list.json()["count"] == 1
    assert resolved_list.json()["items"][0]["status"] == "resolved"


# ===========================================================================
# 4. Filtering and Summary Metrics Verification
# ===========================================================================


def test_filtering_and_summary_metrics(db_client: TestClient) -> None:
    """Filtering GET /api/v1/escalations?status=... and GET /api/v1/audit-logs?escalated_only=true."""
    # Insert 1 non-emergency interaction
    r1 = db_client.post(
        "/api/v1/triage",
        json={"session_id": "sess_non_emerg_1", "user_input": "عندي كحة ناشفة خفيفة بقالها يومين"},
    )
    assert r1.status_code == 200

    # Insert 1 emergency interaction
    r2 = db_client.post(
        "/api/v1/triage",
        json={
            "session_id": "sess_emerg_2",
            "user_input": "حاسس بطابوقة على صدري ومسمعة في دراعي الشمال وعرق بارد مغرقني",
        },
    )
    assert r2.status_code == 200

    # Insert another non-emergency interaction
    r3 = db_client.post(
        "/api/v1/triage",
        json={"session_id": "sess_non_emerg_3", "user_input": "ركبتي بتطقطق لما بطلع السلم"},
    )
    assert r3.status_code == 200

    # 1. Total audit logs should be 3
    audit_resp = db_client.get("/api/v1/audit-logs")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert audit_data["total_count"] == 3
    assert audit_data["escalated_count"] == 1
    assert audit_data["avg_latency_ms"] >= 0
    assert len(audit_data["items"]) == 3

    # 2. Filter escalated_only=true
    esc_audit_resp = db_client.get("/api/v1/audit-logs?escalated_only=true")
    assert esc_audit_resp.status_code == 200
    esc_audit_data = esc_audit_resp.json()
    assert len(esc_audit_data["items"]) == 1
    assert esc_audit_data["items"][0]["session_id"] == "sess_emerg_2"
    assert esc_audit_data["items"][0]["escalation_triggered"] is True

    # 3. Filter escalations by status
    pending_resp = db_client.get("/api/v1/escalations?status=pending")
    assert pending_resp.status_code == 200
    assert pending_resp.json()["count"] == 1

    ack_resp = db_client.get("/api/v1/escalations?status=acknowledged")
    assert ack_resp.status_code == 200
    assert ack_resp.json()["count"] == 0

    resolved_resp = db_client.get("/api/v1/escalations?status=resolved")
    assert resolved_resp.status_code == 200
    assert resolved_resp.json()["count"] == 0


# ===========================================================================
# 5. Root Alias Endpoints Verification
# ===========================================================================


def test_root_alias_endpoints_match_v1(db_client: TestClient) -> None:
    """Root aliases (/escalations, /escalations/{id}, /audit-logs) match API v1 endpoints."""
    # Post emergency interaction via root alias /triage
    triage_resp = db_client.post(
        "/triage",
        json={
            "session_id": "sess_root_alias_01",
            "user_input": "ترجيع دم مستمر بكميات كبيرة مع دوخة وهبوط حاد",
        },
    )
    assert triage_resp.status_code == 200
    assert triage_resp.json()["urgency_level"] == 4

    # Access root alias GET /escalations
    root_esc = db_client.get("/escalations")
    assert root_esc.status_code == 200
    esc_data = root_esc.json()
    assert esc_data["count"] == 1
    alert_id = esc_data["items"][0]["id"]

    # Access root alias PATCH /escalations/{alert_id}
    patch_root = db_client.patch(f"/escalations/{alert_id}", json={"status": "acknowledged"})
    assert patch_root.status_code == 200
    assert patch_root.json()["status"] == "acknowledged"

    # Access root alias GET /audit-logs
    root_audit = db_client.get("/audit-logs")
    assert root_audit.status_code == 200
    assert root_audit.json()["total_count"] == 1
    assert root_audit.json()["escalated_count"] == 1


# ===========================================================================
# 6. Fail-safe SLO-07 when Database is Unavailable
# ===========================================================================


def test_db_unavailable_failsafe_slo07(db_client: TestClient) -> None:
    """When DB is unavailable, GET endpoints return graceful 200 empty responses instead of 500."""
    original_engine = getattr(app.state, "db_engine", None)
    try:
        # Simulate DB engine unavailable
        app.state.db_engine = None

        # GET /api/v1/escalations returns 200 with empty list
        esc_resp = db_client.get("/api/v1/escalations")
        assert esc_resp.status_code == 200
        assert esc_resp.json() == {"items": [], "count": 0}

        # GET /api/v1/audit-logs returns 200 with empty items and zero metrics
        audit_resp = db_client.get("/api/v1/audit-logs")
        assert audit_resp.status_code == 200
        assert audit_resp.json() == {
            "items": [],
            "total_count": 0,
            "escalated_count": 0,
            "avg_latency_ms": 0.0,
        }

        # Root alias GET /escalations returns 200
        root_esc = db_client.get("/escalations")
        assert root_esc.status_code == 200
        assert root_esc.json() == {"items": [], "count": 0}

        # Root alias GET /audit-logs returns 200
        root_audit = db_client.get("/audit-logs")
        assert root_audit.status_code == 200
        assert root_audit.json() == {
            "items": [],
            "total_count": 0,
            "escalated_count": 0,
            "avg_latency_ms": 0.0,
        }

        # PATCH /api/v1/escalations/{id} returns 503 Service Unavailable when DB is down
        patch_resp = db_client.patch(
            "/api/v1/escalations/00000000-0000-0000-0000-000000000000",
            json={"status": "acknowledged"},
        )
        assert patch_resp.status_code == 503
    finally:
        app.state.db_engine = original_engine


# ===========================================================================
# 7. Error Handling on PATCH /api/v1/escalations
# ===========================================================================


def test_patch_escalation_error_handling(db_client: TestClient) -> None:
    """PATCH /api/v1/escalations returns 404 for missing alerts and 422 for malformed payloads."""
    # Non-existent UUID
    missing_uuid = "11111111-2222-3333-4444-555555555555"
    resp_404 = db_client.patch(
        f"/api/v1/escalations/{missing_uuid}",
        json={"status": "acknowledged"},
    )
    assert resp_404.status_code == 404
    assert "not found" in resp_404.json()["detail"].lower()

    # Malformed non-UUID string
    resp_invalid_uuid = db_client.patch(
        "/api/v1/escalations/not-a-valid-uuid",
        json={"status": "acknowledged"},
    )
    assert resp_invalid_uuid.status_code == 404

    # Invalid status transition (e.g. status='deleted')
    resp_invalid_status = db_client.patch(
        f"/api/v1/escalations/{missing_uuid}",
        json={"status": "deleted"},
    )
    assert resp_invalid_status.status_code == 422


# ===========================================================================
# 8. Robustness & Edge Cases: Case-Insensitivity, Short Session ID, Boundaries
# ===========================================================================


def test_case_insensitive_status_and_all_filtering(db_client: TestClient) -> None:
    """Escalation queries and patch payloads handle mixed case and whitespace robustly."""
    triage_resp = db_client.post(
        "/api/v1/triage",
        json={
            "session_id": "sess_case_test_01",
            "user_input": "حاسس بسكاكين في صدري وعرق غزير ومش قادر آخد نفسي",
        },
    )
    assert triage_resp.status_code == 200
    assert triage_resp.json().get("session_id")

    # 1. Query with uppercase ?status=PENDING
    resp_upper = db_client.get("/api/v1/escalations?status=PENDING")
    assert resp_upper.status_code == 200
    assert resp_upper.json()["count"] == 1
    assert resp_upper.json()["items"][0]["status"] == "pending"

    # 2. Query with title case ?status=Pending
    resp_title = db_client.get("/api/v1/escalations?status=Pending")
    assert resp_title.status_code == 200
    assert resp_title.json()["count"] == 1

    # 3. Query with ?status=all
    resp_all = db_client.get("/api/v1/escalations?status=all")
    assert resp_all.status_code == 200
    assert resp_all.json()["count"] == 1

    esc_item_id = resp_upper.json()["items"][0]["id"]

    # 4. PATCH with mixed case payload {"status": "Acknowledged"}
    patch_upper = db_client.patch(
        f"/api/v1/escalations/{esc_item_id}",
        json={"status": "Acknowledged"},
    )
    assert patch_upper.status_code == 200
    assert patch_upper.json()["status"] == "acknowledged"

    # 5. Query with ?status=ACKNOWLEDGED
    resp_ack = db_client.get("/api/v1/escalations?status=ACKNOWLEDGED")
    assert resp_ack.status_code == 200
    assert resp_ack.json()["count"] == 1

    # 6. PATCH with uppercase {"status": "RESOLVED"}
    patch_res = db_client.patch(
        f"/api/v1/escalations/{esc_item_id}",
        json={"status": "  RESOLVED  "},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "resolved"


def test_short_session_id_preserved_verbatim(db_client: TestClient) -> None:
    """Short session_ids (< 8 chars) are not mangled by padding and match exactly in audit-logs."""
    short_sid = "s1"
    triage_resp = db_client.post(
        "/api/v1/triage",
        json={"session_id": short_sid, "user_input": "عندي كحة خفيفة من يومين"},
    )
    assert triage_resp.status_code == 200
    assert triage_resp.json()["session_id"] == short_sid

    audit_resp = db_client.get("/api/v1/audit-logs")
    assert audit_resp.status_code == 200
    items = audit_resp.json()["items"]
    found = next((i for i in items if i["session_id"] == short_sid), None)
    assert found is not None, f"Expected exact session_id '{short_sid}', found items: {items}"
    assert found["session_id"] == short_sid


def test_pagination_limits_and_boundary_checks(db_client: TestClient) -> None:
    """Clamped pagination limits (1..500) and multi-item metric computations work accurately."""
    # Post 2 interactions
    db_client.post(
        "/api/v1/triage",
        json={"session_id": "sess_bound_1", "user_input": "صداع خفيف في الجبهة"},
    )
    db_client.post(
        "/api/v1/triage",
        json={
            "session_id": "sess_bound_2",
            "user_input": "حاسس بطابوقة على صدري ومسمعة في دراعي الشمال وعرق بارد",
        },
    )

    # limit=1 should return exactly 1 item while total_count reflects all items
    resp_l1 = db_client.get("/api/v1/audit-logs?limit=1")
    assert resp_l1.status_code == 200
    data_l1 = resp_l1.json()
    assert len(data_l1["items"]) == 1
    assert data_l1["total_count"] == 2
    assert data_l1["escalated_count"] == 1
    assert data_l1["avg_latency_ms"] >= 0

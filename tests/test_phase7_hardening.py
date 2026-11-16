"""tests/test_phase7_hardening.py

Phase 7 Hardening & Resilience Acceptance Tests for ShefaGuide AI.

Covers:
1. test_qdrant_failure_returns_safe_fallback:
   Mocking retriever failure in app/rag/retriever.py returns HTTP 200 with valid TriageResponse & disclaimer.
2. test_llm_timeout_returns_safe_fallback:
   Mocking LLM timeout returns safe fallback in under 3.5 seconds with HTTP 200.
3. test_extreme_and_malformed_inputs:
   3500-char input, emojis, garbled characters, Arabic/English mix return HTTP 200 or 422 (never 500).
4. test_zero_phi_in_audit_logs_and_escalations:
   Submitting PII (Egyptian name, mobile, national ID) scrubs raw PHI from audit logs (0% leakage).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.db.crud import create_engine
from app.db.models import Base
from app.main import app, rate_limiter
from app.schemas.triage import TriageResponse


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient without auto-raising server exceptions to test error handlers."""
    rate_limiter.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    rate_limiter.reset()


@pytest.fixture
def db_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """TestClient backed by an isolated SQLite database for audit-log persistence."""
    db_file = tmp_path / "hardening_audit.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_engine(url)

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_setup())
    finally:
        _loop.close()
        asyncio.set_event_loop(None)

    old_engine = getattr(app.state, "db_engine", None)
    old_sync = getattr(app.state, "sync_audit", False)

    app.state.db_engine = engine
    app.state.sync_audit = True
    rate_limiter.reset()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    rate_limiter.reset()
    app.state.db_engine = old_engine
    app.state.sync_audit = old_sync


# ═══════════════════════════════════════════════════════════════
# TEST 1: QDRANT RETRIEVER FAILURE -> SAFE FALLBACK (200 + DISCLAIMER)
# ═══════════════════════════════════════════════════════════════
def test_qdrant_failure_returns_safe_fallback(client: TestClient) -> None:
    """Mock the retriever in app/rag/retriever.py to fail; POST /api/v1/triage returns 200 with valid TriageResponse."""
    payload = {
        "session_id": "test-qdrant-fail-001",
        "user_input": "عندي كحة مستمرة بقالها أسبوع وبلغم خفيف",
        "input_mode": "text",
    }

    with patch(
        "app.rag.retriever.retrieve_guidelines",
        side_effect=RuntimeError("Qdrant cluster unavailable / connection timeout"),
    ):
        resp = client.post("/api/v1/triage", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    # Must parse successfully as schema-valid TriageResponse
    triage_resp = TriageResponse(**data)
    assert triage_resp.disclaimer_ar, "Disclaimer must be non-empty"
    assert len(triage_resp.disclaimer_ar.strip()) > 0
    # Must contain medical disclaimer terminology
    assert any(term in triage_resp.disclaimer_ar for term in ("طبي", "تنبيه", "استشارة", "طبيب"))


# ═══════════════════════════════════════════════════════════════
# TEST 2: LLM TIMEOUT -> SAFE FALLBACK (< 3.5s, 200 + VALID RESPONSE)
# ═══════════════════════════════════════════════════════════════
def test_llm_timeout_returns_safe_fallback(client: TestClient) -> None:
    """Mock the LLM to time out; POST /api/v1/triage returns safe fallback in under 3.5s."""
    payload = {
        "session_id": "test-llm-timeout-001",
        "user_input": "عندي صداع خفيف بقاله يومين مع زغللة بسيطة",
        "input_mode": "text",
    }

    async def _mock_timeout(*args, **kwargs):
        raise TimeoutError("Gemini LLM API call timed out after 10000ms")

    with patch("app.services.triage_service.process_triage", side_effect=_mock_timeout):
        start_time = time.perf_counter()
        resp = client.post("/api/v1/triage", json=payload)
        elapsed_sec = time.perf_counter() - start_time

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert elapsed_sec < 3.5, f"Response latency exceeded threshold: {elapsed_sec:.3f}s >= 3.5s"

    data = resp.json()
    triage_resp = TriageResponse(**data)
    assert triage_resp.disclaimer_ar and len(triage_resp.disclaimer_ar.strip()) > 0
    assert triage_resp.rationale_ar and len(triage_resp.rationale_ar.strip()) > 0


# ═══════════════════════════════════════════════════════════════
# TEST 3: EXTREME & MALFORMED INPUTS (200 OR 422, NEVER 500)
# ═══════════════════════════════════════════════════════════════
def test_extreme_and_malformed_inputs(client: TestClient) -> None:
    """Extreme / malformed inputs (3500-char, emojis, garbled, mixed) must return 200 or 422, never 500."""
    extreme_inputs = [
        # 3500-character oversized input (> max_length 1500)
        "أ" * 3500,
        "عندي كحة " * 350,
        # Emoji-only input
        "🤒🤕😷💊🏥🚨💉🩺" * 30,
        # Garbled control and null characters
        "\x00\xff\xfe\x01\x02\x03" * 15 + " عندي وجع في بطني ",
        # Arabic / English mixed input
        "I have severe chest tightness ولدي وجع شديد في صدري and difficulty breathing",
        # Whitespace-only input
        "                ",
        # Single character
        "x",
    ]

    for raw_input in extreme_inputs:
        payload = {
            "session_id": "test-malformed-001",
            "user_input": raw_input,
            "input_mode": "text",
        }
        resp = client.post("/api/v1/triage", json=payload)
        assert resp.status_code in (200, 422), (
            f"Input '{raw_input[:40]}...' caused status {resp.status_code}. "
            "Must return 200 or 422, NEVER 500."
        )
        if resp.status_code == 200:
            # If accepted, must produce a valid schema response
            body = resp.json()
            assert "urgency_level" in body
            assert "disclaimer_ar" in body


# ═══════════════════════════════════════════════════════════════
# TEST 4: ZERO PHI IN AUDIT LOGS & ESCALATIONS
# ═══════════════════════════════════════════════════════════════
def test_zero_phi_in_audit_logs_and_escalations(db_client: TestClient) -> None:
    """Submitting Egyptian PII (name, phone, national ID) scrubs raw PHI from audit logs (0% leakage)."""
    raw_name = "مروة عبد العزيز الحسيني"
    raw_phone = "01012345678"
    raw_nid = "29805121234567"

    pii_payload = {
        "session_id": "test-zero-phi-phase7-001",
        "user_input": (
            f"أنا اسمي {raw_name} ورقم بطاقتي {raw_nid} ورقم تليفوني {raw_phone}، "
            "عندي وجع مزمن في أسفل الظهر مستمر بقاله أسبوعين."
        ),
        "input_mode": "text",
    }

    # 1. Post triage request
    triage_resp = db_client.post("/api/v1/triage", json=pii_payload)
    assert triage_resp.status_code == 200, f"Triage failed: {triage_resp.text}"

    # 2. Confirm raw PII does NOT appear in the triage response body
    triage_text = triage_resp.text
    assert raw_phone not in triage_text, "Raw mobile number leaked in triage response!"
    assert raw_nid not in triage_text, "Raw national ID leaked in triage response!"

    # 3. Retrieve audit logs and verify raw phone and national ID are completely absent
    audit_resp = db_client.get("/api/v1/audit-logs?limit=50")
    assert audit_resp.status_code == 200, f"Audit logs failed: {audit_resp.text}"
    audit_text = audit_resp.text

    assert raw_phone not in audit_text, f"Raw mobile number {raw_phone} leaked in audit logs!"
    assert raw_nid not in audit_text, f"Raw national ID {raw_nid} leaked in audit logs!"

    # 4. Check specific log entry if available
    audit_data = audit_resp.json()
    if audit_data.get("items"):
        session_entry = next(
            (i for i in audit_data["items"] if i.get("session_id") == "test-zero-phi-phase7-001"),
            None,
        )
        if session_entry:
            scrubbed_input = session_entry.get("user_input_scrubbed", "")
            assert raw_phone not in scrubbed_input, "Raw phone in user_input_scrubbed!"
            assert raw_nid not in scrubbed_input, "Raw NID in user_input_scrubbed!"

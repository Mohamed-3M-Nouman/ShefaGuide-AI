"""Comprehensive unit and end-to-end tests for Step 7 Real-Time Zero-PHI SSE Escalation Stream.

Covers:
1. `GET /api/v1/escalations/stream?once=true` (and `/escalations/stream?once=true`) returns 200 OK,
   `content-type: text/event-stream`, `Cache-Control: no-cache`, and the `event: connected` SSE frame.
2. Triggering a Level 4 emergency via `POST /api/v1/triage` automatically publishes a real-time
   `event: escalation` frame to `/api/v1/escalations/stream?once=true` containing `urgency_level: 4`
   and `symptom_category: "cardiopulmonary"`.
3. Zero-PHI Verification on SSE Stream (SLO-08): verifies that raw SSE frames contain ZERO traces
   of patient names ("محمد") or phone numbers ("01098765432").
4. Triggering a Level 4 emergency via `POST /api/v1/voice/triage` (using `fallback_text`) also
   publishes the alert to the SSE stream.
5. `max_events=1`, live subscriber queue push, and `heartbeat` behavior on `EscalationBroadcaster.stream_events`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limiter import rate_limiter
from app.core.sse import EscalationBroadcaster, escalation_broadcaster
from app.main import app
from app.safety.pii_scrubber import contains_pii


def _parse_sse_frames(raw_sse: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE stream text into a list of (event_name, parsed_json_data) tuples."""
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in raw_sse.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = "message"
        data_str = "{}"
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
        frames.append((event_name, json.loads(data_str)))
    return frames


@pytest.fixture(scope="module")
def async_runner() -> Generator[asyncio.Runner, None, None]:
    """Share a single asyncio.Runner for async generator unit tests."""
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture(autouse=True)
def reset_broadcaster_and_limiter() -> Generator[None, None, None]:
    """Reset the SSE broadcaster and rate limiter before and after every test."""
    escalation_broadcaster.reset()
    rate_limiter.reset()
    app.state.db_engine = None
    yield
    escalation_broadcaster.reset()
    rate_limiter.reset()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient instance for synchronous SSE snapshot verification."""
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# 1. SSE Handshake & Headers Verification (`/api/v1/escalations/stream?once=true`)
# ===========================================================================


def test_sse_stream_handshake_and_headers(client: TestClient) -> None:
    """Verify GET /api/v1/escalations/stream?once=true and root alias return 200 OK and connected event."""
    for path in ("/api/v1/escalations/stream?once=true", "/escalations/stream?once=true"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert resp.headers.get("cache-control") == "no-cache"

        frames = _parse_sse_frames(resp.text)
        assert len(frames) == 1
        event_name, data = frames[0]
        assert event_name == "connected"
        assert data["status"] == "connected"
        assert data["service"] == "ShefaGuide AI Escalation Stream"


# ===========================================================================
# 2 & 3. Level 4 Text Triage -> Real-Time SSE Alert + Zero-PHI Verification (SLO-08)
# ===========================================================================


def test_text_triage_emergency_publishes_zero_phi_sse_alert(client: TestClient) -> None:
    """Verify POST /api/v1/triage with red flag + PII publishes scrubbed Level 4 SSE frame with 0% PHI."""
    sensitive_input = (
        "أنا اسمي محمد ورقمي 01098765432 وحاسس بطابوقة على صدري ومسمعة في دراعي الشمال"
    )
    triage_resp = client.post(
        "/api/v1/triage",
        json={
            "session_id": "sess_sse_emg_01",
            "user_input": sensitive_input,
            "input_mode": "text",
        },
    )
    assert triage_resp.status_code == 200
    assert triage_resp.json()["urgency_level"] == 4
    assert triage_resp.json()["escalation_triggered"] is True

    # Fetch SSE stream with once=true
    sse_resp = client.get("/api/v1/escalations/stream?once=true")
    assert sse_resp.status_code == 200
    raw_body = sse_resp.text

    # Zero-PHI Verification (SLO-08): ZERO traces of "محمد" or "01098765432"
    assert "محمد" not in raw_body, "Patient name leaked in SSE stream!"
    assert "01098765432" not in raw_body, "Phone number leaked in SSE stream!"
    assert not contains_pii(raw_body), f"PII detected in raw SSE payload: {raw_body}"

    frames = _parse_sse_frames(raw_body)
    assert len(frames) == 2
    assert frames[0][0] == "connected"

    esc_event_name, esc_data = frames[1]
    assert esc_event_name == "escalation"
    assert esc_data["session_id"] == "sess_sse_emg_01"
    assert esc_data["urgency_level"] == 4
    assert esc_data["symptom_category"] == "cardiopulmonary"
    assert esc_data["status"] == "pending"
    assert len(esc_data["detected_red_flags"]) >= 1
    assert "[REDACTED]" in (esc_data.get("scrubbed_summary") or "")


# ===========================================================================
# 4. Level 4 Voice Triage -> Real-Time SSE Alert Publication
# ===========================================================================


def test_voice_triage_emergency_publishes_sse_alert(client: TestClient) -> None:
    """Verify POST /api/v1/voice/triage with red-flag fallback_text publishes Level 4 SSE alert."""
    voice_resp = client.post(
        "/api/v1/voice/triage",
        json={
            "session_id": "sess_sse_voice_01",
            "fallback_text": "عندي كرشة نفس شديدة وشفايفي مزرقة",
        },
    )
    assert voice_resp.status_code == 200
    voice_data = voice_resp.json()
    assert voice_data["triage"]["urgency_level"] == 4
    assert voice_data["triage"]["escalation_triggered"] is True

    sse_resp = client.get("/escalations/stream?once=true")
    assert sse_resp.status_code == 200
    frames = _parse_sse_frames(sse_resp.text)
    assert len(frames) == 2

    esc_name, esc_payload = frames[1]
    assert esc_name == "escalation"
    assert esc_payload["session_id"] == "sess_sse_voice_01"
    assert esc_payload["urgency_level"] == 4
    assert esc_payload["symptom_category"] == "cardiopulmonary"
    assert esc_payload["status"] == "pending"


# ===========================================================================
# 5. Bounded `max_events=1`, Live Queue Push & `heartbeat` Verification
# ===========================================================================


def test_broadcaster_max_events_and_heartbeat_async(
    async_runner: asyncio.Runner,
) -> None:
    """Verify max_events=1 and heartbeat frame emission on EscalationBroadcaster.stream_events."""
    broadcaster = EscalationBroadcaster(maxlen=10)

    async def _exercise_heartbeat_and_live_push() -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
        # Case A: No events published -> emits `connected` then 1 `heartbeat` when max_events=1
        hb_chunks: list[str] = []
        async for chunk in broadcaster.stream_events(
            replay_recent=False,
            max_events=1,
            once=False,
            heartbeat_interval=0.05,
        ):
            hb_chunks.append(chunk)

        # Case B: Live subscriber receives a newly published escalation immediately and exits at max_events=1
        live_chunks: list[str] = []

        async def _delayed_publish() -> None:
            await asyncio.sleep(0.02)
            broadcaster.publish_escalation(
                {
                    "session_id": "sess_live_sub_01",
                    "symptom_category": "neurological_ent_ophth",
                    "detected_red_flags": ["اعوجاج في الوجه وثقل اللسان"],
                    "urgency_level": 4,
                    "scrubbed_summary": "اسمي سارة ورقمي 01112223334 وعندي ثقل في اللسان",
                }
            )

        pub_task = asyncio.create_task(_delayed_publish())
        async for chunk in broadcaster.stream_events(
            replay_recent=False,
            max_events=1,
            once=False,
            heartbeat_interval=2.0,
        ):
            live_chunks.append(chunk)
        await pub_task

        return _parse_sse_frames("".join(hb_chunks)), _parse_sse_frames("".join(live_chunks))

    hb_frames, live_frames = async_runner.run(_exercise_heartbeat_and_live_push())

    # Verify Case A: connected + 1 heartbeat
    assert len(hb_frames) == 2
    assert hb_frames[0][0] == "connected"
    assert hb_frames[1][0] == "heartbeat"
    assert hb_frames[1][1] == {"type": "heartbeat"}

    # Verify Case B: connected + 1 live escalation with scrubbed PII
    assert len(live_frames) == 2
    assert live_frames[0][0] == "connected"
    assert live_frames[1][0] == "escalation"
    assert live_frames[1][1]["session_id"] == "sess_live_sub_01"
    assert live_frames[1][1]["symptom_category"] == "neurological_ent_ophth"
    assert "01112223334" not in json.dumps(live_frames[1][1], ensure_ascii=False)
    assert "سارة" not in json.dumps(live_frames[1][1], ensure_ascii=False)

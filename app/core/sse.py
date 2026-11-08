"""Real-time Zero-PHI Server-Sent Events (SSE) broadcaster for emergency escalations.

Provides an in-memory, async-safe broadcaster (`EscalationBroadcaster`) that:
1. Scrubs all string fields via `scrub_pii()` and verifies `contains_pii()` is False (SLO-08).
2. Buffers recent Level 4 escalation alerts in a bounded `collections.deque(maxlen=50)`.
3. Pushes real-time SSE frames to connected supervisor dashboard subscribers (`GET /api/v1/escalations/stream`).
4. Supports deterministic bounded streaming (`once=True`, `max_events`, `heartbeat_interval`)
   so both browser `EventSource` clients and synchronous `TestClient` tests complete without deadlocks.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.safety.pii_scrubber import REDACTED_TOKEN, contains_pii, scrub_pii
from app.schemas.triage import SymptomCategory, UrgencyLevel

__all__ = [
    "EscalationBroadcaster",
    "escalation_broadcaster",
    "format_sse_event",
]


def _sanitize_text(value: Any) -> str:
    """Scrub PII from any string value and guarantee 0% PHI leakage."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    scrubbed = scrub_pii(raw)
    if contains_pii(scrubbed):
        return REDACTED_TOKEN
    return scrubbed


def _sanitize_session_id(session_id: Any) -> str:
    """Ensure session_id is an opaque, non-identifying token."""
    raw = str(session_id or "session_fallback").strip()
    if contains_pii(raw):
        return "session_redacted"
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "_", raw)
    if not cleaned:
        return "session_fallback"
    return cleaned[:64]


def format_sse_event(event_name: str, data: dict[str, Any]) -> str:
    """Format an SSE frame (`event: <name>\\ndata: <json>\\n\\n`)."""
    serialized = json.dumps(data, ensure_ascii=False)
    return f"event: {event_name}\ndata: {serialized}\n\n"


class EscalationBroadcaster:
    """Thread/async-safe Zero-PHI SSE broadcaster for Level 4 emergency escalations."""

    def __init__(self, maxlen: int = 50) -> None:
        self._maxlen = maxlen
        self._recent: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def recent_events(self) -> list[dict[str, Any]]:
        """Return a snapshot list of buffered Zero-PHI escalation events."""
        return list(self._recent)

    def reset(self) -> None:
        """Clear buffered events and active subscribers (used in test isolation)."""
        self._recent.clear()
        self._subscribers.clear()

    def publish_escalation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scrub, store, and broadcast a Level 4 emergency escalation payload."""
        raw_cat = payload.get("symptom_category", SymptomCategory.UNKNOWN.value)
        if hasattr(raw_cat, "value"):
            cat_str = str(raw_cat.value)
        else:
            cat_str = _sanitize_text(raw_cat) or SymptomCategory.UNKNOWN.value

        raw_flags = payload.get("detected_red_flags") or []
        if isinstance(raw_flags, (list, tuple, set)):
            scrubbed_flags = [_sanitize_text(f) for f in raw_flags if str(f).strip()]
        else:
            scrubbed_flags = [_sanitize_text(raw_flags)] if str(raw_flags).strip() else []
        if not scrubbed_flags:
            scrubbed_flags = ["Emergency escalation triggered"]

        raw_urg = payload.get("urgency_level", int(UrgencyLevel.EMERGENCY_ESCALATION))
        try:
            urg_int = int(raw_urg)
        except (TypeError, ValueError):
            urg_int = int(UrgencyLevel.EMERGENCY_ESCALATION)

        event: dict[str, Any] = {
            "event_id": str(payload.get("event_id") or uuid.uuid4()),
            "session_id": _sanitize_session_id(payload.get("session_id")),
            "timestamp": str(
                payload.get("timestamp") or datetime.now(UTC).isoformat()
            ),
            "symptom_category": cat_str,
            "recommended_specialty": _sanitize_text(
                payload.get("recommended_specialty")
                or "طوارئ المستشفى فوراً / اتصال بالإسعاف (123)"
            ),
            "detected_red_flags": scrubbed_flags,
            "urgency_level": urg_int,
            "status": _sanitize_text(payload.get("status") or "pending") or "pending",
        }

        if payload.get("scrubbed_summary") is not None:
            event["scrubbed_summary"] = _sanitize_text(payload.get("scrubbed_summary"))

        self._recent.append(event)

        stale_queues: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale_queues.append(queue)
            except Exception:
                stale_queues.append(queue)

        for stale in stale_queues:
            self._subscribers.discard(stale)

        return event

    async def stream_events(
        self,
        replay_recent: bool = True,
        max_events: int | None = None,
        once: bool = False,
        heartbeat_interval: float = 2.0,
    ) -> AsyncIterator[str]:
        """Yield SSE frames for connected supervisor dashboard clients."""
        # 1. Immediate handshake frame
        yield format_sse_event(
            "connected",
            {
                "status": "connected",
                "service": "ShefaGuide AI Escalation Stream",
            },
        )

        emitted = 0

        # 2. Replay buffered recent escalations if requested
        if replay_recent:
            for item in list(self._recent):
                yield format_sse_event("escalation", item)
                emitted += 1
                if max_events is not None and emitted >= max_events:
                    return

        # 3. Deterministic immediate termination for `once=True` (TestClient / snapshot mode)
        if once:
            return

        # 4. Live subscription loop with bounded `max_events` and periodic heartbeat
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while max_events is None or emitted < max_events:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=max(0.05, float(heartbeat_interval))
                    )
                    yield format_sse_event("escalation", event)
                    emitted += 1
                except (asyncio.TimeoutError, TimeoutError):
                    yield format_sse_event("heartbeat", {"type": "heartbeat"})
                    emitted += 1
        finally:
            self._subscribers.discard(queue)


escalation_broadcaster = EscalationBroadcaster(maxlen=50)

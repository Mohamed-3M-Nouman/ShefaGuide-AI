"""Ephemeral Zero-PHI in-memory session store for the multi-turn clarification loop.

Satisfies NFR-01 (Zero PHI caching & privacy) and FR-10 (multi-turn clarifying agent):

* Only PII-scrubbed symptom turns are ever stored (never raw user text).
* Sessions expire after a TTL (default 15 minutes) and the store is capped (LRU/oldest eviction).
* Nothing is persisted to disk; the store lives only in process memory.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from threading import RLock

from app.safety.pii_scrubber import REDACTED_TOKEN, contains_pii, scrub_pii

DEFAULT_TTL_SECONDS: float = 900.0
DEFAULT_MAX_SESSIONS: int = 1000
MAX_CLARIFICATION_TURNS: int = 3
TURN_SEPARATOR: str = " | "
MAX_HISTORY_TURNS: int = 12


@dataclass
class SessionRecord:
    """Zero-PHI state retained for one multi-turn triage conversation."""

    session_id: str
    scrubbed_history: list[str] = field(default_factory=list)
    clarification_count: int = 0
    cumulative_negated_red_flags: list[str] = field(default_factory=list)
    last_urgency: int | None = None
    last_route_taken: str | None = None
    last_retrieved_doc_ids: list[str] = field(default_factory=list)
    last_red_flags_detected: list[str] = field(default_factory=list)
    last_latency_ms: float = 0.0
    recommended_specialty: str | None = None
    symptom_category: str | None = None
    updated_at: float = 0.0


def _guard_scrubbed(text: str) -> str:
    """Scrub `text` and enforce SLO-08: the result must never contain detectable PII/PHI."""
    scrubbed = scrub_pii(text or "")
    if contains_pii(scrubbed):
        # Defensive second pass; if PII still survives, drop the whole turn rather than store PHI.
        scrubbed = scrub_pii(scrubbed)
    if contains_pii(scrubbed):
        scrubbed = REDACTED_TOKEN
    return scrubbed


def _merge_unique(base: Iterable[str], extra: Iterable[str] | None) -> list[str]:
    merged = list(base)
    for item in extra or ():
        if item not in merged:
            merged.append(item)
    return merged


def _copy_record(record: SessionRecord) -> SessionRecord:
    return replace(
        record,
        scrubbed_history=list(record.scrubbed_history),
        cumulative_negated_red_flags=list(record.cumulative_negated_red_flags),
        last_retrieved_doc_ids=list(record.last_retrieved_doc_ids),
        last_red_flags_detected=list(record.last_red_flags_detected),
    )


class EphemeralSessionStore:
    """Thread-safe in-memory session store with TTL expiry and a bounded session count."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_clarification_turns: int = MAX_CLARIFICATION_TURNS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max(1, int(max_sessions))
        self.max_clarification_turns = max_clarification_turns
        self._clock = clock
        # Ordered oldest-updated -> most-recently-updated.
        self._sessions: OrderedDict[str, SessionRecord] = OrderedDict()
        self._lock = RLock()

    # ------------------------------------------------------------------ internals
    def _is_expired(self, record: SessionRecord, now: float) -> bool:
        return (now - record.updated_at) > self.ttl_seconds

    def _purge_expired(self, now: float) -> None:
        expired = [sid for sid, rec in self._sessions.items() if self._is_expired(rec, now)]
        for sid in expired:
            del self._sessions[sid]

    # ------------------------------------------------------------------ public API
    def get_session(self, session_id: str) -> SessionRecord | None:
        """Return a copy of the live session, purging any expired sessions first."""
        with self._lock:
            self._purge_expired(self._clock())
            record = self._sessions.get(session_id)
            return _copy_record(record) if record is not None else None

    def update_session(
        self,
        session_id: str,
        scrubbed_turn: str,
        *,
        negated_red_flags: Iterable[str] | None = None,
        urgency: int | None = None,
        route_taken: str | None = None,
        retrieved_doc_ids: Iterable[str] | None = None,
        red_flags_detected: Iterable[str] | None = None,
        latency_ms: float = 0.0,
        clarification_count: int | None = None,
        recommended_specialty: str | None = None,
        symptom_category: str | None = None,
    ) -> SessionRecord:
        """Append a scrubbed turn (creating the session on first use) and return a copy of the record.

        First message: `clarification_count = 0`. Each later message increments it by 1
        (or adopts `clarification_count` when a higher explicit value is supplied).
        """
        safe_turn = _guard_scrubbed(scrubbed_turn)
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            record = self._sessions.get(session_id)
            if record is None:
                record = SessionRecord(
                    session_id=session_id,
                    scrubbed_history=[safe_turn],
                    clarification_count=max(0, clarification_count or 0),
                )
            else:
                record.scrubbed_history.append(safe_turn)
                if len(record.scrubbed_history) > MAX_HISTORY_TURNS:
                    record.scrubbed_history = record.scrubbed_history[-MAX_HISTORY_TURNS:]
                record.clarification_count = max(record.clarification_count + 1, clarification_count or 0)

            record.cumulative_negated_red_flags = _merge_unique(
                record.cumulative_negated_red_flags, negated_red_flags
            )
            if urgency is not None:
                record.last_urgency = int(urgency)
            if route_taken is not None:
                record.last_route_taken = route_taken
            if retrieved_doc_ids is not None:
                record.last_retrieved_doc_ids = list(retrieved_doc_ids)
            if red_flags_detected is not None:
                record.last_red_flags_detected = list(red_flags_detected)
            if recommended_specialty is not None:
                record.recommended_specialty = _guard_scrubbed(recommended_specialty)
            if symptom_category is not None:
                record.symptom_category = symptom_category
            record.last_latency_ms = float(latency_ms)
            record.updated_at = now

            self._sessions[session_id] = record
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return _copy_record(record)

    def get_combined_scrubbed_input(
        self, session_id: str, new_scrubbed_input: str
    ) -> tuple[str, int]:
        """Return `(combined_scrubbed_text, projected_clarification_count)` for the next turn."""
        new_text = _guard_scrubbed(new_scrubbed_input)
        record = self.get_session(session_id)
        if record is None:
            return new_text, 0
        combined = TURN_SEPARATOR.join([*record.scrubbed_history, new_text])
        return combined, record.clarification_count + 1

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def reset(self) -> None:
        """Drop every session (deterministic test isolation)."""
        with self._lock:
            self._sessions.clear()

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return len(self._sessions)


session_store = EphemeralSessionStore()

__all__ = [
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_TTL_SECONDS",
    "MAX_CLARIFICATION_TURNS",
    "EphemeralSessionStore",
    "SessionRecord",
    "session_store",
]

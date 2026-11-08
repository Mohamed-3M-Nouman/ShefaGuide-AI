"""Async CRUD for the zero-PHI audit log and escalation queue.

Every write path runs patient-derived text through `scrub_pii()` before the row is built and
verifies with `contains_pii()` that nothing identifiable remains (fail-fast). The
`ScrubbedText` / `ScrubbedJSON` column types in `app.db.models` scrub again at bind time as a
safety net.

Functions take an `AsyncSession` and only `flush()`. The caller owns the transaction:

    async with session_factory() as session, session.begin():
        await log_interaction(session, AuditLogCreate(...), detected_red_flags=[...])
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import AuditLog, Base, EscalationQueue, EscalationStatus, scrub_value
from app.safety.pii_scrubber import contains_pii, scrub_pii
from app.schemas.triage import SymptomCategory, UrgencyLevel

DEFAULT_DATABASE_URL: str = "postgresql+asyncpg://shefaguide:shefaguide@localhost:5432/shefaguide"


class PHILeakError(RuntimeError):
    """Raised when text still contains PII after scrubbing; the write is aborted."""


# --------------------------------------------------------------------------- engine / session


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    """Create the async engine (asyncpg for PostgreSQL)."""
    return create_async_engine(url or get_database_url(), pool_pre_ping=True, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create the `audit_logs` and `escalation_queue` tables if they do not exist."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


# --------------------------------------------------------------------------- input schemas


class AuditLogCreate(BaseModel):
    """Data for one triage interaction. Text fields may contain raw patient input; they are scrubbed."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    user_input: str = Field(..., min_length=1)
    symptom_category: SymptomCategory = SymptomCategory.UNKNOWN
    urgency_level: UrgencyLevel
    recommended_specialty: str | None = None
    rationale: str | None = None
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    escalation_triggered: bool = False
    latency_ms: float | None = Field(default=None, ge=0)

    @field_validator("session_id")
    @classmethod
    def _session_id_must_not_be_identifying(cls, value: str) -> str:
        if contains_pii(value):
            raise ValueError("session_id must be an opaque token, not identifying data")
        return value


# --------------------------------------------------------------------------- PHI guard


def scrub_text(text: str | None) -> str | None:
    """Scrub PII from text and fail fast if anything identifiable survives."""
    if text is None:
        return None
    scrubbed = scrub_pii(text)
    if contains_pii(scrubbed):
        raise PHILeakError("PII detected after scrubbing; refusing to persist")
    return scrubbed


def scrub_json(value: Any) -> Any:
    """Recursively scrub every string in a JSON-compatible structure, failing fast on leaks."""
    scrubbed = scrub_value(value)
    _assert_no_pii(scrubbed)
    return scrubbed


def _assert_no_pii(value: Any) -> None:
    if isinstance(value, str):
        if contains_pii(value):
            raise PHILeakError("PII detected after scrubbing; refusing to persist")
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_no_pii(key)
            _assert_no_pii(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_pii(item)


# --------------------------------------------------------------------------- writes


async def create_audit_log(session: AsyncSession, data: AuditLogCreate) -> AuditLog:
    """Persist one anonymized interaction. `user_input` and all other text go through `scrub_pii()`."""
    row = AuditLog(
        session_id=data.session_id,
        scrubbed_input=scrub_text(data.user_input),
        symptom_category=data.symptom_category.value,
        urgency_level=int(data.urgency_level),
        recommended_specialty=scrub_text(data.recommended_specialty),
        rationale=scrub_text(data.rationale),
        retrieved_doc_ids=scrub_json(list(data.retrieved_doc_ids)),
        tool_calls=scrub_json(list(data.tool_calls)),
        escalation_triggered=data.escalation_triggered,
        latency_ms=data.latency_ms,
    )
    session.add(row)
    await session.flush()
    return row


async def enqueue_escalation(
    session: AsyncSession,
    audit_log: AuditLog,
    detected_red_flags: Sequence[str] = (),
    summary: str | None = None,
) -> EscalationQueue:
    """Add an urgent case to the escalation queue, linked to its audit log entry."""
    row = EscalationQueue(
        audit_log_id=audit_log.id,
        session_id=audit_log.session_id,
        symptom_category=audit_log.symptom_category,
        detected_red_flags=scrub_json(list(detected_red_flags)),
        scrubbed_summary=scrub_text(summary),
        status=EscalationStatus.PENDING.value,
    )
    session.add(row)
    await session.flush()
    return row


async def log_interaction(
    session: AsyncSession,
    data: AuditLogCreate,
    detected_red_flags: Sequence[str] = (),
) -> tuple[AuditLog, EscalationQueue | None]:
    """Write the audit log and, for escalated or emergency-level cases, enqueue an escalation.

    Both rows are written in the caller's transaction, so an escalation is never recorded
    without its audit trail.
    """
    audit_log = await create_audit_log(session, data)
    escalation = None
    if data.escalation_triggered or data.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION:
        escalation = await enqueue_escalation(
            session, audit_log, detected_red_flags=detected_red_flags, summary=data.user_input
        )
    return audit_log, escalation


async def update_escalation_status(
    session: AsyncSession, escalation_id: uuid.UUID, status: EscalationStatus
) -> EscalationQueue:
    """Move an escalation through pending -> acknowledged -> resolved."""
    row = await session.get(EscalationQueue, escalation_id)
    if row is None:
        raise LookupError(f"Escalation {escalation_id} not found")
    now = datetime.now(UTC)
    row.status = status.value
    if status is EscalationStatus.ACKNOWLEDGED and row.acknowledged_at is None:
        row.acknowledged_at = now
    elif status is EscalationStatus.RESOLVED:
        row.acknowledged_at = row.acknowledged_at or now
        row.resolved_at = now
    await session.flush()
    return row


# --------------------------------------------------------------------------- reads


async def get_audit_log(session: AsyncSession, audit_log_id: uuid.UUID) -> AuditLog | None:
    return await session.get(AuditLog, audit_log_id)


async def list_escalations(
    session: AsyncSession,
    status: EscalationStatus | None = EscalationStatus.PENDING,
    limit: int = 50,
) -> list[EscalationQueue]:
    """Escalations for the internal dashboard, newest first (pending only by default)."""
    query = select(EscalationQueue).order_by(EscalationQueue.created_at.desc()).limit(limit)
    if status is not None:
        query = query.where(EscalationQueue.status == status.value)
    return list((await session.scalars(query)).all())

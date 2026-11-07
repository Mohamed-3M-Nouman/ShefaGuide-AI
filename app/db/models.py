"""SQLAlchemy 2.0 models for the zero-PHI audit log and escalation queue (PostgreSQL / asyncpg).

ERD:

    audit_logs (1) ──────────────< (0..1) escalation_queue
    ─────────────────────────────          ─────────────────────────────
    id                 UUID PK             id                  UUID PK
    session_id         VARCHAR(64) idx     audit_log_id        UUID FK -> audit_logs.id, unique
    created_at         TIMESTAMPTZ idx     session_id          VARCHAR(64) idx
    scrubbed_input     TEXT                created_at          TIMESTAMPTZ idx
    symptom_category   VARCHAR(32)         symptom_category    VARCHAR(32)
    urgency_level      SMALLINT 1..4       detected_red_flags  JSONB (list[str])
    recommended_spec.  TEXT                scrubbed_summary    TEXT
    rationale          TEXT                status              VARCHAR(16) idx
    retrieved_doc_ids  JSONB (list[str])                       pending | acknowledged | resolved
    tool_calls         JSONB (list[obj])   acknowledged_at     TIMESTAMPTZ
    escalation_trig.   BOOLEAN             resolved_at         TIMESTAMPTZ
    latency_ms         DOUBLE PRECISION

Covers FR-11 (urgent escalation dashboard), FR-12 (anonymized interaction logging) and
NFR-04 (traceability to tool state and RAG document IDs).

Zero-PHI: every free-text column uses `ScrubbedText` and every JSON column uses
`ScrubbedJSON`. Both run `scrub_pii()` at bind time, so no write path, including raw ORM use
that bypasses `app.db.crud`, can persist identifiable data. The CRUD layer also scrubs
explicitly before it builds the rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.safety.pii_scrubber import scrub_pii


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def scrub_value(value: Any) -> Any:
    """Recursively apply `scrub_pii` to every string in a JSON-compatible structure."""
    if isinstance(value, str):
        return scrub_pii(value)
    if isinstance(value, dict):
        return {scrub_value(key): scrub_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_value(item) for item in value]
    return value


class ScrubbedText(TypeDecorator[str]):
    """TEXT column that always stores the PII-scrubbed version of its value."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else scrub_pii(str(value))


class ScrubbedJSON(TypeDecorator[Any]):
    """JSON column (JSONB on PostgreSQL) whose string values are PII-scrubbed before storage."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return None if value is None else scrub_value(value)


class EscalationStatus(str, Enum):
    """Lifecycle of an urgent case on the internal escalation dashboard."""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Base(DeclarativeBase):
    """Declarative base for all ShefaGuide tables."""


class AuditLog(Base):
    """One anonymized triage interaction (FR-12)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("urgency_level BETWEEN 1 AND 4", name="ck_audit_logs_urgency_level"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_audit_logs_latency"),
        Index("ix_audit_logs_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    scrubbed_input: Mapped[str] = mapped_column(ScrubbedText, nullable=False)
    symptom_category: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    urgency_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recommended_specialty: Mapped[str | None] = mapped_column(ScrubbedText)
    rationale: Mapped[str | None] = mapped_column(ScrubbedText)
    retrieved_doc_ids: Mapped[list[str]] = mapped_column(ScrubbedJSON, nullable=False, default=list)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(ScrubbedJSON, nullable=False, default=list)
    escalation_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)

    escalation: Mapped[EscalationQueue | None] = relationship(
        back_populates="audit_log", uselist=False, cascade="all, delete-orphan"
    )


class EscalationQueue(Base):
    """An urgent / red-flag case awaiting supervisor action (FR-10, FR-11)."""

    __tablename__ = "escalation_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'acknowledged', 'resolved')", name="ck_escalation_queue_status"
        ),
        Index("ix_escalation_queue_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audit_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_logs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    symptom_category: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    detected_red_flags: Mapped[list[str]] = mapped_column(ScrubbedJSON, nullable=False, default=list)
    scrubbed_summary: Mapped[str | None] = mapped_column(ScrubbedText)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EscalationStatus.PENDING.value, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    audit_log: Mapped[AuditLog] = relationship(back_populates="escalation")

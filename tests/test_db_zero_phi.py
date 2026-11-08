"""Zero-PHI acceptance tests for `audit_logs` / `escalation_queue` (`app/db`).

Acceptance criterion: a record containing sensitive data is stored as `[REDACTED]`, with 0% leakage.

Tests run on SQLite (aiosqlite) by default. Set TEST_DATABASE_URL (e.g.
postgresql+asyncpg://user:pass@localhost:5432/shefaguide_test) to run them against PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.crud import (
    AuditLogCreate,
    PHILeakError,
    create_audit_log,
    create_engine,
    create_session_factory,
    init_db,
    list_escalations,
    log_interaction,
    scrub_text,
    update_escalation_status,
)
from app.db.models import AuditLog, Base, EscalationStatus
from app.safety.pii_scrubber import REDACTED_TOKEN, contains_pii, scrub_pii
from app.schemas.triage import SymptomCategory, UrgencyLevel

T = TypeVar("T")

SENSITIVE_VALUES: list[str] = [
    "طارق عبد الرحمن",
    "01098765432",
    "+20 112 345 6789",
    "29208151200456",
    "tarek.abdelrahman@example.com",
    "Tarek Hassan",
]
SENSITIVE_INPUT = (
    "أنا اسمي طارق عبد الرحمن ورقم موبايلي 01098765432 وتليفون البيت +20 112 345 6789 "
    "والرقم القومي 29208151200456 والإيميل tarek.abdelrahman@example.com، "
    "حاسس بطابوقة على صدري والوجع مسمع في دراعي الشمال."
)


def _run(scenario: Callable[[async_sessionmaker[AsyncSession]], Awaitable[T]], tmp_path: Path) -> T:
    async def runner() -> T:
        url = os.getenv("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}"
        engine = create_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
            await init_db(engine)
            return await scenario(create_session_factory(engine))
        finally:
            await engine.dispose()

    # `asyncio.Runner` instead of `asyncio.run`: `eval/run_eval.py` replaces `asyncio.run` on
    # import with a loop-less shim that cannot drive real I/O such as database drivers.
    with asyncio.Runner() as loop_runner:
        return loop_runner.run(runner())


def _strings(value: Any) -> list[str]:
    """Every string stored in a raw column value; JSON text is decoded so escaped Arabic is checked."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return [value]
        return [value] if isinstance(decoded, str) else _strings(decoded)
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return []


async def _raw_rows(session: AsyncSession, table: str) -> list[dict[str, Any]]:
    result = await session.execute(text(f"SELECT * FROM {table}"))
    return [dict(row) for row in result.mappings().all()]


def _sensitive_record() -> AuditLogCreate:
    return AuditLogCreate(
        session_id="sess_9f8e7d6c5b4a",
        user_input=SENSITIVE_INPUT,
        symptom_category=SymptomCategory.CARDIOPULMONARY,
        urgency_level=UrgencyLevel.EMERGENCY_ESCALATION,
        recommended_specialty="طوارئ المستشفى فوراً (قسم القلب والعناية المركزة)",
        rationale="My name is Tarek Hassan and the patient reports crushing chest pain.",
        retrieved_doc_ids=["NHS-CARDIO-001", "WHO-CARDIO-005"],
        tool_calls=[
            {
                "tool": "symptom_severity_tool",
                "input": {"complaint": SENSITIVE_INPUT, "callback": "01098765432"},
                "output": {"urgency": 4, "contact": "tarek.abdelrahman@example.com"},
            }
        ],
        escalation_triggered=True,
        latency_ms=812.5,
    )


def test_sensitive_record_is_stored_redacted_with_zero_leakage(tmp_path: Path) -> None:
    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        async with factory() as session, session.begin():
            await log_interaction(
                session,
                _sensitive_record(),
                detected_red_flags=["طابوقة على صدري - اتصل بي على 01098765432"],
            )

        async with factory() as session:
            audit_rows = await _raw_rows(session, "audit_logs")
            queue_rows = await _raw_rows(session, "escalation_queue")

        assert len(audit_rows) == 1 and len(queue_rows) == 1
        stored = [s for row in audit_rows + queue_rows for s in _strings(list(row.values()))]

        leaks = [value for value in SENSITIVE_VALUES if any(value in s for s in stored)]
        leakage_rate = len(leaks) / len(SENSITIVE_VALUES)
        assert leakage_rate == 0.0, f"PHI leaked: {leaks}"
        assert not any(contains_pii(s) for s in stored)

        audit = audit_rows[0]
        assert REDACTED_TOKEN in audit["scrubbed_input"]
        assert audit["scrubbed_input"] == scrub_pii(SENSITIVE_INPUT)
        assert "طابوقة على صدري" in audit["scrubbed_input"]  # clinical content is preserved
        assert REDACTED_TOKEN in audit["rationale"]
        assert REDACTED_TOKEN in json.dumps(_strings(audit["tool_calls"]), ensure_ascii=False)
        assert REDACTED_TOKEN in queue_rows[0]["scrubbed_summary"]
        assert REDACTED_TOKEN in _strings(queue_rows[0]["detected_red_flags"])[0]

    _run(scenario, tmp_path)


def test_orm_writes_that_bypass_crud_are_still_scrubbed(tmp_path: Path) -> None:
    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        async with factory() as session, session.begin():
            session.add(
                AuditLog(
                    session_id="sess_raw_orm_write",
                    scrubbed_input=SENSITIVE_INPUT,
                    urgency_level=4,
                    tool_calls=[{"note": "رقمي 01098765432"}],
                )
            )
        async with factory() as session:
            stored = _strings(list((await _raw_rows(session, "audit_logs"))[0].values()))
        assert not any(value in s for value in SENSITIVE_VALUES for s in stored)
        assert any(REDACTED_TOKEN in s for s in stored)

    _run(scenario, tmp_path)


def test_non_emergency_interaction_is_not_enqueued(tmp_path: Path) -> None:
    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        async with factory() as session, session.begin():
            _, escalation = await log_interaction(
                session,
                AuditLogCreate(
                    session_id="sess_routine_0001",
                    user_input="اسمي منى علي وعندي حرقان ونار قايدة في فم المعدة",
                    symptom_category=SymptomCategory.GASTROINTESTINAL,
                    urgency_level=UrgencyLevel.ROUTINE_SPECIALIST,
                    retrieved_doc_ids=["NHS-GI-001"],
                ),
            )
        assert escalation is None
        async with factory() as session:
            assert await _raw_rows(session, "escalation_queue") == []
            audit = (await _raw_rows(session, "audit_logs"))[0]
        assert "منى" not in audit["scrubbed_input"]
        assert REDACTED_TOKEN in audit["scrubbed_input"]

    _run(scenario, tmp_path)


def test_escalation_status_lifecycle(tmp_path: Path) -> None:
    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        async with factory() as session, session.begin():
            _, escalation = await log_interaction(session, _sensitive_record(), ["ألم ضاغط في الصدر"])
            assert escalation is not None
            escalation_id = escalation.id

        async with factory() as session:
            pending = await list_escalations(session)
            assert [row.id for row in pending] == [escalation_id]
            assert pending[0].status == EscalationStatus.PENDING.value

        async with factory() as session, session.begin():
            row = await update_escalation_status(session, escalation_id, EscalationStatus.RESOLVED)
            assert row.acknowledged_at is not None and row.resolved_at is not None

        async with factory() as session:
            assert await list_escalations(session) == []
            resolved = await list_escalations(session, status=EscalationStatus.RESOLVED)
            assert [row.id for row in resolved] == [escalation_id]

    _run(scenario, tmp_path)


def test_identifying_session_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AuditLogCreate(
            session_id="29208151200456",
            user_input="عندي صداع",
            urgency_level=UrgencyLevel.ROUTINE_SPECIALIST,
        )


def test_scrub_text_fails_fast_if_pii_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.db.crud.scrub_pii", lambda value: value)  # simulate a broken scrubber
    with pytest.raises(PHILeakError):
        scrub_text("رقمي 01098765432")


def test_create_audit_log_never_writes_when_scrubbing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.crud.scrub_pii", lambda value: value)

    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        with pytest.raises(PHILeakError):
            async with factory() as session, session.begin():
                await create_audit_log(session, _sensitive_record())
        async with factory() as session:
            assert await _raw_rows(session, "audit_logs") == []

    _run(scenario, tmp_path)


def test_main_persist_audit_log_background_task(tmp_path: Path) -> None:
    from app.main import app, persist_audit_log
    from app.schemas.triage import SourceCitation, TriageResponse

    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        app.state.db_engine = factory.kw["bind"]

        fake_resp = TriageResponse(
            session_id="test_session_123",
            urgency_level=UrgencyLevel.EMERGENCY_4,
            recommended_specialty="طوارئ",
            symptom_category=SymptomCategory.CARDIOPULMONARY,
            rationale_ar="طوارئ فوراً",
            clarifying_questions=[],
            negated_red_flags=[],
            citations=[
                SourceCitation(
                    doc_id="NHS-CARDIO-001",
                    source="NHS",
                    title="Chest Pain",
                    url="https://nhs.uk/chest-pain",
                    snippet="Call 999",
                )
            ],
            disclaimer_ar="تنبيه طبي",
            escalation_triggered=True,
        )

        await persist_audit_log(
            session_id="test_session_123",
            user_input="حاسس بطابوقة على صدري",
            response=fake_resp,
            latency_ms=12.5,
        )

        async with factory() as session:
            logs = await _raw_rows(session, "audit_logs")
            assert len(logs) == 1
            assert logs[0]["session_id"] == "test_session_123"
            assert logs[0]["escalation_triggered"] in (True, 1)

            escalations = await _raw_rows(session, "escalation_queue")
            assert len(escalations) == 1
            assert escalations[0]["session_id"] == "test_session_123"
            assert escalations[0]["status"] == "pending"

        app.state.db_engine = None

    _run(scenario, tmp_path)


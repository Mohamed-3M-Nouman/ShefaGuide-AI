"""Step 10: NFR-04 clinical traceability endpoint and GitHub Actions CI pipeline checks."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent import session_store
from app.core.rate_limiter import rate_limiter
from app.db.crud import create_engine
from app.db.models import Base
from app.main import app
from app.safety.pii_scrubber import contains_pii

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(autouse=True)
def isolate_state() -> Generator[None, None, None]:
    session_store.reset()
    rate_limiter.reset()
    yield
    session_store.reset()
    rate_limiter.reset()


@pytest.fixture
def db_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """TestClient backed by an isolated SQLite audit DB with synchronous audit persistence."""
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'step10_audit.db'}")

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    with asyncio.Runner() as runner:
        runner.run(_setup())

    original_engine = getattr(app.state, "db_engine", None)
    app.state.db_engine = engine
    app.state.sync_audit = True
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.db_engine = original_engine

    async def _teardown() -> None:
        await engine.dispose()

    with asyncio.Runner() as runner:
        runner.run(_teardown())


def test_traceability_endpoint_tracks_clinical_assessment_and_qdrant_doc_ids(
    db_client: TestClient,
) -> None:
    """Clinical turn is traceable end-to-end (route, doc_ids, audit rows) with zero PHI."""
    post = db_client.post(
        "/api/v1/triage",
        json={
            "session_id": "trace-gi-01",
            "user_input": "أنا اسمي سامي ورقمي 01012345678 وعندي حرقان في فم المعدة بيزيد بعد الأكل",
        },
    )
    assert post.status_code == 200, post.text
    triage = post.json()

    for path in ("/api/v1/traceability/trace-gi-01", "/traceability/trace-gi-01"):
        resp = db_client.get(path)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["session_id"] == "trace-gi-01"
        assert data["trace_found"] is True
        assert data["zero_phi_verified"] is True
        assert data["route_taken"] == "clinical_assessment"
        assert data["clarification_count"] == 0
        assert len(data["retrieved_doc_ids"]) >= 1
        assert data["retrieved_doc_ids"] == [c["doc_id"] for c in triage["citations"]]
        assert data["urgency_level"] == triage["urgency_level"]
        assert data["recommended_specialty"] == triage["recommended_specialty"]
        assert data["symptom_category"] == "gastrointestinal"
        assert data["execution_latency_ms"] > 0
        assert len(data["audit_log_records"]) == 1
        assert data["audit_log_records"][0]["retrieved_doc_ids"] == data["retrieved_doc_ids"]

        blob = json.dumps(data, ensure_ascii=False)
        assert "سامي" not in blob
        assert "01012345678" not in blob
        assert "[REDACTED]" in blob
        assert not contains_pii(blob.replace("[REDACTED]", ""))


def test_traceability_endpoint_tracks_multi_turn_and_red_flag_escalation(
    db_client: TestClient,
) -> None:
    """Multi-turn context and the mid-conversation Level 4 fast-path are fully traceable."""
    sid = "trace-mt-02"
    first = db_client.post(
        "/api/v1/triage", json={"session_id": sid, "user_input": "حاسس بشوية دوخة بسيطة"}
    )
    assert first.status_code == 200, first.text
    assert first.json()["urgency_level"] < 4

    second = db_client.post(
        "/api/v1/triage",
        json={"session_id": sid, "user_input": "دلوقتي حاسس بطابوقة على صدري وعرق غزير"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["urgency_level"] == 4

    resp = db_client.get(f"/api/v1/traceability/{sid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["clarification_count"] == 1
    assert len(data["scrubbed_history"]) == 2
    assert data["urgency_level"] == 4
    assert data["route_taken"] == "fast_path_emergency"
    assert data["red_flags_detected"]
    assert data["zero_phi_verified"] is True
    assert len(data["audit_log_records"]) == 2
    assert data["audit_log_records"][0]["escalation_triggered"] is True  # most recent first


def test_traceability_endpoint_returns_404_for_unknown_session(db_client: TestClient) -> None:
    """Unknown session ids return a structured 404 on both the v1 and root alias paths."""
    for path in (
        "/api/v1/traceability/non-existent-session-999",
        "/traceability/non-existent-session-999",
    ):
        resp = db_client.get(path)
        assert resp.status_code == 404
        data = resp.json()
        assert data["trace_found"] is False
        assert data["session_id"] == "non-existent-session-999"
        assert data["detail"] == "No traceability record found for session_id"


def test_traceability_degrades_gracefully_without_audit_database() -> None:
    """With no audit DB (or a broken one) the in-memory session_store still serves the trace."""
    original_engine = getattr(app.state, "db_engine", None)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.db_engine = None
            post = client.post(
                "/api/v1/triage",
                json={"session_id": "trace-nodb-03", "user_input": "عندي حرقان في فم المعدة"},
            )
            assert post.status_code == 200, post.text
            resp = client.get("/api/v1/traceability/trace-nodb-03")
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["trace_found"] is True
            assert data["trace_source"] == "session_store"
            assert data["audit_log_records"] == []
            assert data["recommended_specialty"]
            assert data["symptom_category"] == "gastrointestinal"

            class _BrokenEngine:  # any DB failure must never surface as a 500
                pass

            app.state.db_engine = _BrokenEngine()
            broken = client.get("/api/v1/traceability/trace-nodb-03")
            assert broken.status_code == 200, broken.text
            assert broken.json()["trace_source"] == "session_store"
    finally:
        app.state.db_engine = original_engine


def test_session_store_records_specialty_and_category_in_ram() -> None:
    """SessionRecord carries the complete clinical decision picture without any DB flush."""
    from app.agent import run_triage_agent_sync
    from app.schemas.triage import TriageRequest

    response = run_triage_agent_sync(
        TriageRequest(session_id="trace-ram-04", user_input="عندي حرقان في فم المعدة")
    )
    record = session_store.get_session("trace-ram-04")
    assert record is not None
    assert record.recommended_specialty == response.recommended_specialty
    assert record.symptom_category == response.symptom_category.value


def test_github_actions_ci_workflow_exists_and_valid() -> None:
    """`.github/workflows/ci.yml` exists and encodes the lint -> test -> eval quality gate."""
    assert CI_WORKFLOW_PATH.is_file(), "missing .github/workflows/ci.yml"
    text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # PyYAML is optional; fall back to structural text checks
        yaml = None

    if yaml is not None:
        doc = yaml.safe_load(text)
        triggers = doc.get("on", doc.get(True))  # PyYAML parses bare `on` as boolean True
        assert "push" in triggers and "pull_request" in triggers
        assert triggers["push"]["branches"] == ["main", "master", "feat/**", "track/**"]
        assert triggers["pull_request"]["branches"] == ["main", "master"]
        job = doc["jobs"]["lint-test-and-eval"]
        assert job["runs-on"] == "ubuntu-latest"
        assert job["timeout-minutes"] == 10
        uses = [s.get("uses") for s in job["steps"] if "uses" in s]
        assert "actions/checkout@v4" in uses
        assert "actions/setup-python@v5" in uses
    else:
        for token in ("on:", "push:", "pull_request:", "jobs:", "lint-test-and-eval:"):
            assert token in text

    for required in (
        "ruff check app/ tests/ eval/",
        "pytest --ignore=tests/test_hybrid_retriever.py -q",
        "python eval/run_eval.py",
        "pip install -r requirements.txt",
        "ubuntu-latest",
    ):
        assert required in text
    assert "\t" not in text, "YAML must not contain tab indentation"

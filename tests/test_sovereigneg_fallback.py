"""Unit and integration tests for the 3-tier LLM resilience chain:
Tier 1 (Google Gemini Primary) -> Tier 2 (SovereignEG OpenAI-Compatible Fallback) -> Tier 3 (Deterministic Safe Fallback).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.agent.tools as agent_tools
from app.agent import (
    SeverityAssessmentOutput,
    SpecialtyMappingOutput,
    set_agent_llm,
    specialty_mapping_tool,
    symptom_severity_tool,
)
from app.core.config import (
    GEMINI_MODEL,
    SOVEREIGNEG_API_KEY,
    SOVEREIGNEG_BASE_URL,
    SOVEREIGNEG_MODEL,
    settings,
)
from app.core.rate_limiter import rate_limiter
from app.main import app
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SymptomCategory,
    TriageResponse,
    UrgencyLevel,
)
from app.services.triage_service import get_default_citation

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FakeResourceExhaustedError(Exception):
    """Simulated Google Gemini HTTP 429 / ResourceExhausted quota error."""


class _StructuredCallable:
    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def invoke(self, prompt: str) -> Any:
        return self._handler(prompt)


class _MockFailingGemini:
    def __init__(self, error: Exception, init_kwargs: dict[str, Any] | None = None) -> None:
        self.error = error
        self.init_kwargs = init_kwargs or {}
        self.calls: list[str] = []

    def with_structured_output(self, schema: type) -> _StructuredCallable:
        def _run(prompt: str) -> Any:
            self.calls.append(schema.__name__)
            raise self.error

        return _StructuredCallable(_run)


class _MockSovereignEGChatOpenAI:
    def __init__(
        self,
        *,
        responses: dict[type, Any] | None = None,
        error: Exception | None = None,
        init_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.error = error
        self.init_kwargs = init_kwargs or {}
        self.calls: list[tuple[str, str | None]] = []

    def with_structured_output(
        self, schema: type, method: str | None = None
    ) -> _StructuredCallable:
        def _run(prompt: str) -> Any:
            self.calls.append((schema.__name__, method))
            if self.error is not None:
                raise self.error
            return self.responses[schema]

        return _StructuredCallable(_run)


@pytest.fixture(autouse=True)
def _reset_cached_clients_and_hooks(monkeypatch: pytest.MonkeyPatch):
    """Ensure cached LLM instances and injected hooks never leak across tests."""
    set_agent_llm(None)
    rate_limiter.reset()
    monkeypatch.setattr(agent_tools, "_CACHED_LLM", None)
    monkeypatch.setattr(agent_tools, "_CACHED_LLM_SIG", None)
    monkeypatch.setattr(agent_tools, "_CACHED_SOVEREIGNEG_LLM", None)
    monkeypatch.setattr(agent_tools, "_CACHED_SOVEREIGNEG_SIG", None)
    yield
    set_agent_llm(None)
    rate_limiter.reset()


def test_sovereigneg_config_env_example_and_requirements() -> None:
    """Verify SovereignEG configuration defaults, .env.example documentation, and requirements.txt."""
    assert settings.GEMINI_MODEL == "gemini-3.8-flash"
    assert GEMINI_MODEL == "gemini-3.8-flash"
    assert settings.SOVEREIGNEG_BASE_URL == "https://backend.sovereigneg.com/v1"
    assert SOVEREIGNEG_BASE_URL == "https://backend.sovereigneg.com/v1"
    assert bool(settings.SOVEREIGNEG_MODEL.strip())
    assert isinstance(SOVEREIGNEG_MODEL, str) and len(SOVEREIGNEG_MODEL) > 0
    assert isinstance(SOVEREIGNEG_API_KEY, str)

    env_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("SOVEREIGNEG_API_KEY=", "SOVEREIGNEG_BASE_URL=", "SOVEREIGNEG_MODEL="):
        assert key in env_text, f"Missing {key} in .env.example"

    req_text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "langchain-openai" in req_text


def test_tier1_429_quota_error_falls_back_to_sovereigneg(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When Google Gemini raises 429 ResourceExhausted and SOVEREIGNEG_API_KEY is set,
    automatically route to SovereignEG ChatOpenAI and return valid structured output."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(settings, "SOVEREIGNEG_API_KEY", "fake-sovereigneg-key")
    monkeypatch.setattr(settings, "SOVEREIGNEG_BASE_URL", "https://backend.sovereigneg.com/v1")
    monkeypatch.setattr(settings, "SOVEREIGNEG_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(agent_tools, "_has_live_gemini_key", lambda: True)
    monkeypatch.setattr(agent_tools, "_has_live_sovereigneg_key", lambda: True)

    captured_gemini_kwargs: list[dict[str, Any]] = []
    captured_openai_kwargs: list[dict[str, Any]] = []

    expected_severity = SeverityAssessmentOutput(
        assessed_urgency=UrgencyLevel.ROUTINE_SPECIALIST,
        symptom_category=SymptomCategory.GASTROINTESTINAL,
        red_flag_suspected=False,
        clinical_reasoning_ar="أعراض حموضة وارتجاع مستقرة تحتاج متابعة تخصص الجهاز الهضمي.",
    )
    expected_specialty = SpecialtyMappingOutput(
        recommended_specialty_ar="أمراض الجهاز الهضمي والكبد",
        rationale_ar="بناءً على الأعراض المذكورة، يُنصح بمراجعة طبيب الجهاز الهضمي للتقييم الإكلينيكي.",
        clarifying_questions=["هل الأعراض بتزيد بعد الأكل الدسم؟"],
        selected_doc_ids=["NHS-GI-001"],
    )

    failing_gemini = _MockFailingGemini(
        FakeResourceExhaustedError("429 ResourceExhausted: Quota exceeded for quota metric")
    )
    sovereigneg_mock = _MockSovereignEGChatOpenAI(
        responses={
            SeverityAssessmentOutput: expected_severity,
            SpecialtyMappingOutput: expected_specialty,
        }
    )

    def _fake_gemini_ctor(**kwargs: Any) -> _MockFailingGemini:
        captured_gemini_kwargs.append(kwargs)
        failing_gemini.init_kwargs = kwargs
        return failing_gemini

    def _fake_openai_ctor(**kwargs: Any) -> _MockSovereignEGChatOpenAI:
        captured_openai_kwargs.append(kwargs)
        sovereigneg_mock.init_kwargs = kwargs
        return sovereigneg_mock

    with (
        patch("langchain_google_genai.ChatGoogleGenerativeAI", side_effect=_fake_gemini_ctor),
        patch("langchain_openai.ChatOpenAI", side_effect=_fake_openai_ctor),
        caplog.at_level(logging.WARNING, logger="shefaguide.agent.tools"),
    ):
        sev = symptom_severity_tool("عندي حرقان في فم المعدة بعد الأكل")
        spec = specialty_mapping_tool(
            scrubbed_input="عندي حرقان في فم المعدة بعد الأكل",
            symptom_category=sev.symptom_category,
            assessed_urgency=sev.assessed_urgency,
            retrieved_citations=[get_default_citation("NHS-GI-001")],
        )

    assert sev == expected_severity
    assert spec.recommended_specialty_ar == expected_specialty.recommended_specialty_ar
    assert spec.selected_doc_ids == ["NHS-GI-001"]

    # Verify Tier 1 config (Google Gemini requires >= 10s deadline; no retries)
    assert len(captured_gemini_kwargs) == 1
    assert captured_gemini_kwargs[0]["timeout"] == 15.0
    assert captured_gemini_kwargs[0]["max_retries"] == 0

    # Verify Tier 2 SovereignEG OpenAI-compatible config
    assert len(captured_openai_kwargs) == 1
    assert captured_openai_kwargs[0]["base_url"] == "https://backend.sovereigneg.com/v1"
    assert captured_openai_kwargs[0]["model"] == "gemini-2.5-flash"
    assert captured_openai_kwargs[0]["api_key"] == "fake-sovereigneg-key"
    assert captured_openai_kwargs[0]["temperature"] == 0.3
    assert captured_openai_kwargs[0]["timeout"] == 20.0
    assert captured_openai_kwargs[0]["max_retries"] == 0

    # Verify both structured calls hit Tier 2 with function_calling
    assert sovereigneg_mock.calls == [
        ("SeverityAssessmentOutput", "json_mode"),
        ("SpecialtyMappingOutput", "json_mode"),
    ]
    assert any(
        "Primary Google Gemini unavailable/exhausted; falling back to SovereignEG" in rec.message
        for rec in caplog.records
    )


def test_tier1_missing_key_skips_to_sovereigneg_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When primary GEMINI_API_KEY is missing, POST /api/v1/triage seamlessly uses SovereignEG."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "SOVEREIGNEG_API_KEY", "fake-sovereigneg-key")
    monkeypatch.setattr(agent_tools, "_has_live_gemini_key", lambda: False)
    monkeypatch.setattr(agent_tools, "_has_live_sovereigneg_key", lambda: True)

    sovereigneg_mock = _MockSovereignEGChatOpenAI(
        responses={
            SeverityAssessmentOutput: SeverityAssessmentOutput(
                assessed_urgency=UrgencyLevel.ROUTINE_SPECIALIST,
                symptom_category=SymptomCategory.GASTROINTESTINAL,
                red_flag_suspected=False,
                clinical_reasoning_ar="أعراض حموضة مستقرة.",
            ),
            SpecialtyMappingOutput: SpecialtyMappingOutput(
                recommended_specialty_ar="أمراض الجهاز الهضمي",
                rationale_ar="يُنصح بمتابعة طبيب الجهاز الهضمي لتقييم الأعراض.",
                clarifying_questions=["منذ متى تشعر بهذه الأعراض؟"],
                selected_doc_ids=["NHS-GI-001"],
            ),
        }
    )

    with patch("langchain_openai.ChatOpenAI", return_value=sovereigneg_mock):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/triage",
            json={
                "session_id": "sovereigneg-e2e-001",
                "user_input": "عندي حموضة وحرقان في المعدة بعد الأكل",
                "input_mode": "text",
            },
        )

    assert resp.status_code == 200
    parsed = TriageResponse.model_validate(resp.json())
    assert parsed.recommended_specialty == "أمراض الجهاز الهضمي"
    assert parsed.symptom_category == SymptomCategory.GASTROINTESTINAL
    assert parsed.disclaimer_ar == DEFAULT_DISCLAIMER_AR


def test_tier1_and_tier2_both_fail_reaches_tier3_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both Google Gemini (429) and SovereignEG (Timeout) fail, Tier 3 deterministic fallback succeeds (SLO-07)."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(settings, "SOVEREIGNEG_API_KEY", "fake-sovereigneg-key")
    monkeypatch.setattr(agent_tools, "_has_live_gemini_key", lambda: True)
    monkeypatch.setattr(agent_tools, "_has_live_sovereigneg_key", lambda: True)

    failing_gemini = _MockFailingGemini(FakeResourceExhaustedError("429 Quota Exceeded"))
    failing_sovereigneg = _MockSovereignEGChatOpenAI(
        error=TimeoutError("SovereignEG 3.0s request timeout")
    )

    with (
        patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=failing_gemini),
        patch("langchain_openai.ChatOpenAI", return_value=failing_sovereigneg),
    ):
        sev = symptom_severity_tool("عندي حرقان في فم المعدة بعد الأكل")
        spec = specialty_mapping_tool(
            scrubbed_input="عندي حرقان في فم المعدة بعد الأكل",
            symptom_category=sev.symptom_category,
            assessed_urgency=sev.assessed_urgency,
        )

        client = TestClient(app)
        resp = client.post(
            "/api/v1/triage",
            json={
                "session_id": "tier3-fallback-001",
                "user_input": "عندي حرقان ونار قايدة في فم المعدة بعد الأكل",
                "input_mode": "text",
            },
        )

    assert sev.symptom_category == SymptomCategory.GASTROINTESTINAL
    assert "الجهاز الهضمي" in spec.recommended_specialty_ar
    assert len(spec.selected_doc_ids) >= 1

    assert resp.status_code == 200
    parsed = TriageResponse.model_validate(resp.json())
    assert parsed.session_id == "tier3-fallback-001"
    assert parsed.symptom_category == SymptomCategory.GASTROINTESTINAL
    assert parsed.disclaimer_ar == DEFAULT_DISCLAIMER_AR
    assert len(parsed.citations) >= 1

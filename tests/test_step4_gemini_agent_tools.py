"""Step 4 unit and integration tests for Gemini 2.5 Flash Structured-Output Agent Tools (`app/agent/tools.py`)."""

from __future__ import annotations

from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.agent import (
    SeverityAssessmentOutput,
    SpecialtyMappingOutput,
    TriageState,
    assess_with_agent_tools,
    clinical_assessment_node,
    invoke_triage_graph_state,
    set_agent_llm,
    set_clinical_assessor_hook,
    specialty_mapping_tool,
    symptom_severity_tool,
)
from app.core.rate_limiter import rate_limiter
from app.main import app
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SymptomCategory,
    TriageRequest,
    TriageResponse,
    UrgencyLevel,
)
from app.services.triage_service import get_default_citation


class MockStructuredRunnable:
    """Mock runnable returned by `MockGeminiLLM.with_structured_output(schema)`."""

    def __init__(self, schema: type, handler: Any) -> None:
        self.schema = schema
        self.handler = handler
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        if callable(self.handler):
            return self.handler(self.schema, prompt)
        return self.handler


class MockGeminiLLM:
    """Mock Gemini 2.5 Flash LLM client supporting `.with_structured_output(schema)`."""

    def __init__(
        self,
        severity_response: Any = None,
        specialty_response: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.severity_response = severity_response
        self.specialty_response = specialty_response
        self.error = error
        self.invocations: list[tuple[str, str]] = []

    def with_structured_output(self, schema: type) -> MockStructuredRunnable:
        def _dispatch(s: type, prompt: str) -> Any:
            self.invocations.append((s.__name__, prompt))
            if self.error is not None:
                raise self.error
            if s is SeverityAssessmentOutput:
                return self.severity_response
            if s is SpecialtyMappingOutput:
                return self.specialty_response
            raise ValueError(f"Unsupported schema: {s}")

        return MockStructuredRunnable(schema, _dispatch)


@pytest.fixture(autouse=True)
def reset_agent_and_rate_limiter_state():
    """Reset injected LLM, clinical assessor hook, and rate limiter before and after each test."""
    set_agent_llm(None)
    set_clinical_assessor_hook(None)
    rate_limiter.reset()
    yield
    set_agent_llm(None)
    set_clinical_assessor_hook(None)
    rate_limiter.reset()


def test_symptom_severity_tool_with_mocked_structured_llm() -> None:
    """1. Verify symptom_severity_tool invokes .with_structured_output(SeverityAssessmentOutput)."""
    expected = SeverityAssessmentOutput(
        assessed_urgency=UrgencyLevel.URGENT_SPECIALIST,
        symptom_category=SymptomCategory.GASTROINTESTINAL,
        red_flag_suspected=False,
        clinical_reasoning_ar="أعراض مغص مراري حاد بعد الأكل الدسم تستدعي فحص الجهاز الهضمي.",
    )
    mock_llm = MockGeminiLLM(severity_response=expected)

    result = symptom_severity_tool(
        scrubbed_input="عندي مغص في جنبي اليمين تحت الضلوع بعد الأكل الدسم",
        matched_slang_terms=[{"slang_id": "EG-GI-009", "clinical_term_ar": "مغص مراري"}],
        llm=mock_llm,
    )

    assert isinstance(result, SeverityAssessmentOutput)
    assert result.assessed_urgency == UrgencyLevel.URGENT_2
    assert result.symptom_category == SymptomCategory.GASTROINTESTINAL
    assert result.red_flag_suspected is False
    assert len(mock_llm.invocations) == 1
    assert mock_llm.invocations[0][0] == "SeverityAssessmentOutput"


def test_specialty_mapping_tool_with_mocked_structured_llm() -> None:
    """2. Verify specialty_mapping_tool maps retrieved citations to Arabic specialty and clarifying questions."""
    citation = get_default_citation("NHS-GI-002")
    expected = SpecialtyMappingOutput(
        recommended_specialty_ar="أمراض الجهاز الهضمي والكبد والمناظير",
        rationale_ar="بناءً على الأعراض المذكورة، يُنصح بمراجعة طبيب الجهاز الهضمي والكبد لعمل سونار على البطن.",
        clarifying_questions=[
            "هل الوجع بيسمع في الكتف اليمين؟",
            "هل في أي اصفرار في العين؟",
        ],
        selected_doc_ids=["NHS-GI-002"],
    )
    mock_llm = MockGeminiLLM(specialty_response=expected)

    result = specialty_mapping_tool(
        scrubbed_input="عندي مغص في جنبي اليمين تحت الضلوع",
        symptom_category=SymptomCategory.GASTROINTESTINAL,
        assessed_urgency=UrgencyLevel.URGENT_SPECIALIST,
        retrieved_citations=[citation],
        llm=mock_llm,
    )

    assert isinstance(result, SpecialtyMappingOutput)
    assert result.recommended_specialty_ar == "أمراض الجهاز الهضمي والكبد والمناظير"
    assert len(result.clarifying_questions) == 2
    assert result.selected_doc_ids == ["NHS-GI-002"]
    assert len(mock_llm.invocations) == 1
    assert mock_llm.invocations[0][0] == "SpecialtyMappingOutput"


def test_supremacy_rule_prevents_llm_from_downgrading_rule_urgency() -> None:
    """3. Prove that if rule_urgency > llm_urgency, final_urgency is strictly max(rule, llm)."""
    mock_llm = MockGeminiLLM(
        severity_response=SeverityAssessmentOutput(
            assessed_urgency=UrgencyLevel.ROUTINE_1,  # LLM attempts to downgrade to Level 1
            symptom_category=SymptomCategory.CARDIOPULMONARY,
            red_flag_suspected=False,
            clinical_reasoning_ar="أعراض بسيطة.",
        ),
        specialty_response=SpecialtyMappingOutput(
            recommended_specialty_ar="الأمراض الصدرية والجهاز التنفسي",
            rationale_ar="يُنصح بحجز كشف لدى طبيب الصدرية لتقييم الحالة.",
            clarifying_questions=["من امتى الكحة بدأت؟"],
            selected_doc_ids=["NHS-CARDIO-004"],
        ),
    )
    set_agent_llm(mock_llm)

    # State has rule_urgency = URGENT_2 (or AMBIGUOUS_SEE_DOCTOR = 3)
    state: TriageState = {
        "session_id": "step4-supremacy-001",
        "scrubbed_input": "عندي كحة مستمرة ونهجان",
        "normalized_input": "عندي كحه مستمره ونهجان",
        "rule_urgency": UrgencyLevel.URGENT_2,
        "negated_red_flags": [],
        "retrieved_citations": [get_default_citation("NHS-CARDIO-004")],
    }

    out = clinical_assessment_node(state)
    assert out["llm_urgency"] == UrgencyLevel.ROUTINE_1
    assert out["final_urgency"] == UrgencyLevel.URGENT_2
    assert out["response"].urgency_level == UrgencyLevel.URGENT_2


def test_llm_escalation_allowed_when_llm_urgency_exceeds_rule_urgency() -> None:
    """4. Prove that if rule_urgency is ROUTINE_1 and Gemini escalates to URGENT_2 or EMERGENCY_4, final_urgency escalates."""
    mock_llm = MockGeminiLLM(
        severity_response=SeverityAssessmentOutput(
            assessed_urgency=UrgencyLevel.URGENT_2,
            symptom_category=SymptomCategory.NEUROLOGICAL_ENT_OPHTH,
            red_flag_suspected=True,  # Subtle red flag suspected -> escalates to EMERGENCY_4
            clinical_reasoning_ar="اشتباه في علامة عصبية حادة تستوجب الطوارئ.",
        ),
        specialty_response=SpecialtyMappingOutput(
            recommended_specialty_ar="طوارئ المخ والأعصاب",
            rationale_ar="نظراً لوجود أعراض عصبية حادة، يجب التوجه فوراً إلى طوارئ المستشفى للفحص العاجل.",
            clarifying_questions=[],
            selected_doc_ids=["NHS-NEURO-001"],
        ),
    )
    set_agent_llm(mock_llm)

    req = TriageRequest(
        session_id="step4-escalate-001",
        user_input="عندي دوخة غريبة وزغللة في عيني من ساعة",
        input_mode="text",
    )
    final_state = invoke_triage_graph_state(req)

    assert final_state["final_urgency"] == UrgencyLevel.EMERGENCY_4
    assert final_state["response"].urgency_level == UrgencyLevel.EMERGENCY_4
    assert final_state["response"].escalation_triggered is True


@pytest.mark.parametrize(
    "unsafe_llm_rationale",
    [
        "تشخيصك النهائي هو التهاب اللوزتين الحاد ويجب الراحة.",
        "أنت مصاب بـ قرحة المعدة، خذ دواء أوميبرازول 20 مجم كل يوم.",
        "يُنصح بتناول أوجمنتين 1000 مجم قرص كل 12 ساعة مع بانادول.",
    ],
)
def test_unsafe_llm_rationale_is_sanitized_to_prevent_schema_violation(
    unsafe_llm_rationale: str,
) -> None:
    """5. Prove that if a mocked LLM outputs forbidden diagnosis or medication names, it is sanitized safely."""
    mock_llm = MockGeminiLLM(
        severity_response=SeverityAssessmentOutput(
            assessed_urgency=UrgencyLevel.ROUTINE_1,
            symptom_category=SymptomCategory.GASTROINTESTINAL,
            red_flag_suspected=False,
            clinical_reasoning_ar="تقييم روتيني.",
        ),
        specialty_response=SpecialtyMappingOutput(
            recommended_specialty_ar="أمراض الجهاز الهضمي والباطنة العامة",
            rationale_ar=unsafe_llm_rationale,
            clarifying_questions=["هل الأعراض بتزيد بعد الأكل؟"],
            selected_doc_ids=["NHS-GI-001"],
        ),
    )
    set_agent_llm(mock_llm)

    req = TriageRequest(
        session_id="step4-sanitize-001",
        user_input="عندي حموضة وحرقان في المعدة بعد الأكل",
        input_mode="text",
    )
    final_state = invoke_triage_graph_state(req)
    resp = final_state["response"]

    # TriageResponse validation succeeded without raising ValueError
    assert isinstance(resp, TriageResponse)
    assert "أوجمنتين" not in resp.rationale_ar
    assert "تشخيصك النهائي" not in resp.rationale_ar
    assert "أوميبرازول" not in resp.rationale_ar
    assert "أمراض الجهاز الهضمي والباطنة العامة" in resp.rationale_ar


def test_llm_timeout_or_api_error_gracefully_falls_back_slo07() -> None:
    """6. Simulate TimeoutError inside Gemini client and verify 200 OK TriageResponse fallback."""
    mock_llm = MockGeminiLLM(error=TimeoutError("Simulated Gemini API 10s timeout"))
    set_agent_llm(mock_llm)

    client = TestClient(app)
    payload = {
        "session_id": "step4-timeout-001",
        "user_input": "عندي حرقان ونار قايدة في فم المعدة بعد الأكل التقيل",
        "input_mode": "text",
    }
    response = client.post("/api/v1/triage", json=payload)
    assert response.status_code == 200

    parsed = TriageResponse.model_validate(response.json())
    assert parsed.session_id == "step4-timeout-001"
    assert parsed.symptom_category == SymptomCategory.GASTROINTESTINAL
    assert len(parsed.citations) >= 1
    assert parsed.disclaimer_ar == DEFAULT_DISCLAIMER_AR

"""Gemini 2.5 Flash Structured-Output Agent Tools for ShefaGuide AI (FR-07 & FR-09)."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.state import TriageState
from app.core.config import settings
from app.safety.red_flags import normalize_arabic
from app.schemas.triage import (
    FORBIDDEN_DIAGNOSIS_PATTERNS,
    FORBIDDEN_MEDICATION_PATTERNS,
    SourceCitation,
    SymptomCategory,
    UrgencyLevel,
)
from app.services.triage_service import (
    _infer_non_emergency_route,
    get_default_citation,
)

logger = logging.getLogger("shefaguide.agent.tools")

SEVERITY_SYSTEM_PROMPT: str = (
    "أنت نظام فرز طبي إكلينيكي محافظ (Conservative Clinical Triage Assessor) مخصص للمرضى في مصر. "
    "مهمتك تقييم مدى خطورة الأعراض وتحديد درجة الاستعجال الطبي فقط مع الانحياز الكامل لسلامة المريض:\n"
    "- 1 (ROUTINE_SPECIALIST): أعراض مستقرة أو مزمنة تحتاج حجز عيادة تخصصية.\n"
    "- 2 (URGENT_SPECIALIST): أعراض حادة غير مهددة للحياة فوراً تحتاج كشف تخصصي عاجل في نفس اليوم.\n"
    "- 3 (AMBIGUOUS_SEE_DOCTOR): أعراض غير واضحة أو متداخلة تتطلب فحصاً طبياً مباشراً لدى طبيب.\n"
    "- 4 (EMERGENCY_ESCALATION): أي اشتباه في علامة خطر تهدد الحياة يستوجب طوارئ المستشفى فوراً.\n"
    "يُمنع منعاً باتاً إصدار تشخيص مرضي نهائي أو ذكر أي أسماء أدوية أو جرعات دوائية."
)

SPECIALTY_SYSTEM_PROMPT: str = (
    "أنت أداة توجيه للتخصصات الطبية (Clinical Specialty Mapping Tool) للمرضى باللهجة المصرية. "
    "بناءً على الأعراض والمراجع الطبية المعتمدة (WHO / NHS / Mayo Clinic)، حدد:\n"
    "1. التخصص الطبي الدقيق باللغة العربية (recommended_specialty_ar).\n"
    "2. تبرير إرشادي مبسط باللغة العربية (rationale_ar) يوضح سبب التوجيه لهذا التخصص دون أي تشخيص نهائي "
    "ودون ذكر أي أسماء أدوية أو مضادات حيوية أو مسكنات أو جرعات.\n"
    "3. حتى 3 أسئلة استيضاحية (clarifying_questions) لمساعدة المريض عند مقابلة الطبيب.\n"
    "4. معرفات المراجع الطبية المستخدمة (selected_doc_ids)."
)


class SeverityAssessmentOutput(BaseModel):
    """Structured output contract for `symptom_severity_tool` (FR-07)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    assessed_urgency: UrgencyLevel = Field(
        ...,
        description="Assessed clinical urgency level (1=Routine, 2=Urgent, 3=Ambiguous/See Doctor, 4=Emergency).",
    )
    symptom_category: SymptomCategory = Field(
        ...,
        description="High-level symptom category.",
    )
    red_flag_suspected: bool = Field(
        default=False,
        description="True if any subtle acute red flag is suspected.",
    )
    clinical_reasoning_ar: str = Field(
        ...,
        min_length=5,
        description="Brief Arabic clinical reasoning for the urgency classification.",
    )


class SpecialtyMappingOutput(BaseModel):
    """Structured output contract for `specialty_mapping_tool` (FR-09)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recommended_specialty_ar: str = Field(
        ...,
        min_length=2,
        description="Recommended medical specialty in Arabic.",
    )
    rationale_ar: str = Field(
        ...,
        min_length=5,
        description="Plain Arabic triage rationale without definitive diagnosis or medication names.",
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Up to 3 follow-up clarifying questions in Arabic.",
    )
    selected_doc_ids: list[str] = Field(
        default_factory=list,
        description="IDs of clinical guideline documents supporting the referral.",
    )


def is_rationale_safe(rationale_ar: str) -> bool:
    """Return True if `rationale_ar` complies with ethical diagnosis and medication guardrails."""
    if not rationale_ar or len(rationale_ar.strip()) < 5:
        return False
    for pattern in FORBIDDEN_DIAGNOSIS_PATTERNS:
        if pattern.search(rationale_ar):
            return False
    for pattern in FORBIDDEN_MEDICATION_PATTERNS:
        if pattern.search(rationale_ar):
            return False
    return True


def sanitize_rationale_ar(rationale_ar: str, recommended_specialty_ar: str) -> str:
    """Ensure `rationale_ar` never violates `FORBIDDEN_DIAGNOSIS_PATTERNS` or `FORBIDDEN_MEDICATION_PATTERNS`."""
    cleaned = (rationale_ar or "").strip()
    if is_rationale_safe(cleaned):
        return cleaned
    safe_specialty = (recommended_specialty_ar or "طبيب مختص").strip()
    return (
        f"بناءً على الأعراض المذكورة، يُنصح بحجز كشف لدى تخصص {safe_specialty} "
        "لإجراء الفحص الإكلينيكي وتقييم الحالة بدقة."
    )


def _has_live_gemini_key() -> bool:
    """Return True if a real, non-placeholder GEMINI_API_KEY is configured."""
    key = (settings.GEMINI_API_KEY or "").strip()
    return bool(key and key != "your_gemini_api_key_here")


def _build_default_gemini_llm() -> Any | None:
    """Instantiate `ChatGoogleGenerativeAI` when a live API key is configured."""
    if not _has_live_gemini_key():
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.0,
            max_retries=1,
        )
    except Exception as exc:
        logger.warning("Failed to initialize ChatGoogleGenerativeAI: %s", exc)
        return None


def symptom_severity_tool(
    scrubbed_input: str,
    matched_slang_terms: list[dict[str, Any]] | None = None,
    llm: Any | None = None,
) -> SeverityAssessmentOutput:
    """FR-07 Conservative Severity Assessment Tool using Gemini structured output with deterministic fallback."""
    norm_input = normalize_arabic(scrubbed_input or "")
    det_category, det_specialty, det_urgency, _, _ = _infer_non_emergency_route(norm_input)

    active_llm = llm if llm is not None else _build_default_gemini_llm()
    if active_llm is not None:
        try:
            structured_llm = active_llm.with_structured_output(SeverityAssessmentOutput)
            slang_context = json.dumps(matched_slang_terms or [], ensure_ascii=False)
            prompt = (
                f"{SEVERITY_SYSTEM_PROMPT}\n\n"
                f"شكوى المريض (بعد تنقية البيانات الشخصية): {scrubbed_input}\n"
                f"المصطلحات العامية المرصودة: {slang_context}"
            )
            result = structured_llm.invoke(prompt)
            if isinstance(result, SeverityAssessmentOutput):
                assessed = result
            elif isinstance(result, dict):
                assessed = SeverityAssessmentOutput.model_validate(result)
            else:
                raise TypeError(f"Unexpected structured output type: {type(result)}")

            if assessed.red_flag_suspected:
                assessed = SeverityAssessmentOutput(
                    assessed_urgency=UrgencyLevel.EMERGENCY_ESCALATION,
                    symptom_category=assessed.symptom_category,
                    red_flag_suspected=True,
                    clinical_reasoning_ar=assessed.clinical_reasoning_ar,
                )
            return assessed
        except Exception as exc:
            logger.warning("symptom_severity_tool fallback triggered due to LLM error: %s", exc)

    return SeverityAssessmentOutput(
        assessed_urgency=det_urgency,
        symptom_category=det_category,
        red_flag_suspected=(det_urgency == UrgencyLevel.EMERGENCY_ESCALATION),
        clinical_reasoning_ar=(
            f"تقييم تحفظي مبدئي للأعراض يوجه إلى تخصص {det_specialty} لدرجة استعجال ({int(det_urgency)})."
        ),
    )


def specialty_mapping_tool(
    scrubbed_input: str,
    symptom_category: SymptomCategory,
    assessed_urgency: UrgencyLevel,
    retrieved_citations: list[SourceCitation] | None = None,
    llm: Any | None = None,
) -> SpecialtyMappingOutput:
    """FR-09 Specialty-Recommendation Tool using Gemini structured output with deterministic fallback."""
    norm_input = normalize_arabic(scrubbed_input or "")
    _, det_specialty, _, det_citations, det_questions = _infer_non_emergency_route(norm_input)

    available_citations = list(retrieved_citations or []) or list(det_citations)
    if not available_citations:
        available_citations = [get_default_citation("NHS-SYS-005")]

    active_llm = llm if llm is not None else _build_default_gemini_llm()
    if active_llm is not None:
        try:
            structured_llm = active_llm.with_structured_output(SpecialtyMappingOutput)
            citations_summary = [
                {"doc_id": c.doc_id, "source": c.source, "title": c.title, "snippet": c.snippet}
                for c in available_citations
            ]
            prompt = (
                f"{SPECIALTY_SYSTEM_PROMPT}\n\n"
                f"شكوى المريض: {scrubbed_input}\n"
                f"تصنيف الأعراض: {symptom_category.value}\n"
                f"درجة الاستعجال المبدئية: {int(assessed_urgency)}\n"
                f"المراجع الطبية المتاحة: {json.dumps(citations_summary, ensure_ascii=False)}"
            )
            result = structured_llm.invoke(prompt)
            if isinstance(result, SpecialtyMappingOutput):
                mapped = result
            elif isinstance(result, dict):
                mapped = SpecialtyMappingOutput.model_validate(result)
            else:
                raise TypeError(f"Unexpected structured output type: {type(result)}")

            safe_rationale = sanitize_rationale_ar(
                mapped.rationale_ar,
                mapped.recommended_specialty_ar,
            )
            selected_ids = list(mapped.selected_doc_ids) or [
                c.doc_id for c in available_citations
            ]
            return SpecialtyMappingOutput(
                recommended_specialty_ar=mapped.recommended_specialty_ar,
                rationale_ar=safe_rationale,
                clarifying_questions=list(mapped.clarifying_questions)[:3],
                selected_doc_ids=selected_ids,
            )
        except Exception as exc:
            logger.warning("specialty_mapping_tool fallback triggered due to LLM error: %s", exc)

    safe_rationale = sanitize_rationale_ar(
        f"بناءً على الأعراض المذكورة، يُنصح بحجز كشف لدى تخصص {det_specialty} "
        "لإجراء الفحص الإكلينيكي وتقييم الحالة بدقة.",
        det_specialty,
    )
    return SpecialtyMappingOutput(
        recommended_specialty_ar=det_specialty,
        rationale_ar=safe_rationale,
        clarifying_questions=list(det_questions)[:3],
        selected_doc_ids=[c.doc_id for c in det_citations]
        or [c.doc_id for c in available_citations],
    )


def assess_with_agent_tools(
    state: TriageState,
    llm: Any | None = None,
) -> tuple[SymptomCategory, str, UrgencyLevel, list[SourceCitation], list[str], str]:
    """Execute FR-07 & FR-09 agent tools and return normalized assessment tuple for `clinical_assessment_node`."""
    scrubbed_input = state.get("scrubbed_input", "")
    matched_slang = state.get("matched_slang_terms", [])
    retrieved_citations = list(state.get("retrieved_citations", []))

    severity_out = symptom_severity_tool(
        scrubbed_input=scrubbed_input,
        matched_slang_terms=matched_slang,
        llm=llm,
    )

    mapping_out = specialty_mapping_tool(
        scrubbed_input=scrubbed_input,
        symptom_category=severity_out.symptom_category,
        assessed_urgency=severity_out.assessed_urgency,
        retrieved_citations=retrieved_citations,
        llm=llm,
    )

    # Resolve selected citations into SourceCitation objects
    citations_by_id = {c.doc_id: c for c in retrieved_citations}
    resolved_citations: list[SourceCitation] = []
    for doc_id in mapping_out.selected_doc_ids:
        if doc_id in citations_by_id:
            resolved_citations.append(citations_by_id[doc_id])
        else:
            resolved_citations.append(get_default_citation(doc_id))

    if not resolved_citations:
        resolved_citations = retrieved_citations or [get_default_citation("NHS-SYS-005")]

    safe_rationale = sanitize_rationale_ar(
        mapping_out.rationale_ar,
        mapping_out.recommended_specialty_ar,
    )

    return (
        severity_out.symptom_category,
        mapping_out.recommended_specialty_ar,
        severity_out.assessed_urgency,
        resolved_citations,
        list(mapping_out.clarifying_questions)[:3],
        safe_rationale,
    )

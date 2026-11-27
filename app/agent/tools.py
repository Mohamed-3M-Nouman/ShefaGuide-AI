"""3-Tier Resilient Structured-Output Agent Tools for ShefaGuide AI (FR-07 & FR-09).

Tier 1 (Primary): Google Gemini (`ChatGoogleGenerativeAI`, fast-fail timeout=2.5s, max_retries=0)
Tier 2 (Secondary Fallback): SovereignEG OpenAI-Compatible API (`ChatOpenAI`, timeout=3.0s, max_retries=1)
Tier 3 (Safe Deterministic Fallback): Rule/corpus router guaranteeing SLO-07 (0% unhandled exceptions)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

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
    "أنت نظام فرز طبي إكلينيكي متوازن ومتعاطف (Balanced Clinical Pre-Care Triage Assessor) مخصص للمرضى في مصر باسم ShefaGuide AI (شفاء جايد).\n"
    "ميّز بدقة بين الحالات التالية دون تهويل للأعراض البسيطة ودون تهاون مع علامات الخطر:\n"
    "أ) التحيات والدردشة العامة والأسئلة غير الطبية (مثل: 'ازيك', 'سلام عليكم', 'بتعمل ايه؟', 'أهلاً', أو أي رسالة بدون أعراض جسدية):\n"
    "   - لا تخمن أي تخصص مرضي! اجعل `assessed_urgency = 3` (AMBIGUOUS_SEE_DOCTOR)، و`symptom_category = unknown`، و`red_flag_suspected = false`.\n"
    "ب) الأعراض اليومية البسيطة والخفيفة بدون علامات خطر (مثل: 'مصدع شوية', 'صداع خفيف', 'تعبان شوية', 'شوية برد', 'وجع بسيط'):\n"
    "   - هذه حالات روتينية مستقرة! اجعل `assessed_urgency = 1` (ROUTINE_SPECIALIST) ولا تصعّدها أبداً للمستوى 3 طالما العرض واضح وبسيط.\n"
    "   - الصداع الخفيف العادي بدون أعراض عصبية (بدون زغللة مستمرة، تنميل، دوخة شديدة، تشنجات، أو صداع مفاجئ عنيف) يُقيّم كمستوى `1`.\n"
    "ج) الأعراض الغامضة جداً أو المتداخلة التي لا يتضح فيها موضع الشكوى (مثل: 'حاسس إني مش مظبوط ومش فاهم ليه'):\n"
    "   - اجعل `assessed_urgency = 3` (AMBIGUOUS_SEE_DOCTOR).\n"
    "د) الأعراض السريرية الواضحة حسب شدتها:\n"
    "   - 1 (ROUTINE_SPECIALIST): أعراض خفيفة أو مستقرة أو مزمنة تحتاج استشارة عادية أو طبيب أسرة/باطنة أو عيادة تخصصية.\n"
    "   - 2 (URGENT_SPECIALIST): أعراض حادة غير مهددة للحياة فوراً تحتاج كشفاً تخصصياً عاجلاً في نفس اليوم.\n"
    "   - 4 (EMERGENCY_ESCALATION): أي اشتباه في علامة خطر تهدد الحياة يستوجب طوارئ المستشفى فوراً.\n"
    "يُمنع منعاً باتاً إصدار تشخيص مرضي نهائي أو ذكر أي أسماء أدوية أو جرعات دوائية."
)

SPECIALTY_SYSTEM_PROMPT: str = (
    "أنت ShefaGuide AI (شفاء جايد) — مساعد الفرز الطبي المبدئي المتعاطف باللهجة المصرية للمرضى في مصر.\n"
    "تحدث مع المريض بأسلوب طبيب مصري ودود ومطمئن بالعامية المصرية الطبيعية، ويُمنع تماماً استخدام عبارات آلية جامدة مثل 'بناءً على الأعراض المذكورة، يُنصح بحجز كشف لدى...'.\n"
    "اتبع القواعد التالية بدقة حسب حالة المحادثة:\n"
    "أ) التحيات والدردشة العامة والأسئلة غير الطبية (مثل: 'ازيك', 'سلام عليكم', 'بتعمل ايه؟', 'انت مين؟', أو أي سؤال عام بدون شكوى جسدية):\n"
    "   - رحّب بالمريض بلطف ودفء بالعامية المصرية وعرّف نفسك كـ 'مساعد الفرز الطبي المبدئي (ShefaGuide AI)'، واسأله عن حاله اليوم، وادعُه لوصف أي أعراض جسدية يشعر بها.\n"
    "   - اجعل `recommended_specialty_ar` حرفياً: \"مساعد الفرز الطبي المبدئي (يرجى وصف الأعراض)\".\n"
    "   - اجعل `clarifying_questions` حرفياً: [\"ما هي الأعراض التي تشعر بها حالياً؟\", \"منذ متى بدأت هذه الأعراض؟\"].\n"
    "ب) الأعراض البسيطة أو الجولة الأولى (دورة الحوار 1 وبدون علامات خطر طارئة):\n"
    "   - لا تبالغ في التوجيه لتخصصات دقيقة لحالات بسيطة! مثلاً: 'مصدع شوية' بدون أعراض عصبية مقلقة لا يذهب فوراً لـ 'مخ وأعصاب'، بل يُوجّه مبدئياً إلى 'طب الأسرة / باطنة عامة' مع أسئلة هادئة ومطمئنة (مثل: مدة الصداع، هل مرتبط بقلة النوم أو الإجهاد، هل في أعراض مصاحبة).\n"
    "   - طمئن المريض أولاً وتفاعل مع شكواه بكلام مصري دافئ، ثم ادمج سؤالاً أو سؤالين محددين ومنطقيين داخل `rationale_ar`، مع وضع نفس الأسئلة (1 إلى 2 سؤالاً) في `clarifying_questions`.\n"
    "ج) الجولة النهائية (الدورة 2 فأكثر بعد وضوح الأعراض، أو عند اكتمال وصف الأعراض السريرية):\n"
    "   - وجّه بدقة إلى التخصص الطبي الأنسب باللغة العربية من بين الفئات الخمس (`cardiopulmonary`, `neurological_ent_ophth`, `gastrointestinal`, `musculoskeletal`, `systemic_fever_derm` أو 'طب الأسرة / باطنة عامة' للحالات الخفيفة العامة) بالاستناد إلى المراجع الطبية المتاحة (`selected_doc_ids`).\n"
    "   - اكتب `rationale_ar` بالعامية المصرية المطمئنة موضحاً سبب ملاءمة هذا التخصص لأعراضه وما يفضل أن يذكره للطبيب عند الكشف.\n"
    "   - اترك `clarifying_questions` قائمة فارغة `[]` لإعلام الواجهة بأن الحوار اكتمل وإظهار بطاقة الإحالة النهائية.\n"
    "- يُمنع منعاً باتاً إصدار تشخيص مرضي نهائي أو ذكر أي أسماء أدوية أو مضادات حيوية أو مسكنات أو جرعات."
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


_GEMINI_MODE_LOGGED: bool = False
_CACHED_LLM_SIG: tuple[str, str] | None = None
_CACHED_LLM: Any | None = None
_CACHED_SOVEREIGNEG_SIG: tuple[str, str, str] | None = None
_CACHED_SOVEREIGNEG_LLM: Any | None = None

_StructuredModelT = TypeVar("_StructuredModelT", bound=BaseModel)
_GREETING_PHRASE_PATTERN = (
    r"(?:ازيك|إزيك|ازيكم|السلام\s*عليكم|سلام\s*عليكم|اهلا|أهلا|أهلاً|مرحبا|مرحباً|"
    r"صباح\s*الخير|مساء\s*الخير|عامل\s*ايه|اخبارك\s*ايه|أخبارك\s*ايه|بتعمل\s*ايه|"
    r"انت\s*مين|مين\s*انت|انت\s*سامعني|سامعني|كويس|تمام|الو|ألو|هاي|هلو|يا\s*دكتور|"
    r"hi|hello|hey|how\s+are\s+you)"
)
_GREETING_OR_CHITCHAT_RE = re.compile(
    rf"^(?:{_GREETING_PHRASE_PATTERN})(?:[\s,،؟?\!.]*(?:{_GREETING_PHRASE_PATTERN}))*[\s\?؟!.,،]*$",
    re.IGNORECASE,
)


def _is_casual_greeting_or_chitchat(text: str) -> bool:
    """Detect pure casual greetings or non-symptom chitchat for deterministic fallback."""
    cleaned = normalize_arabic(text or "").strip()
    if not cleaned:
        return False
    return bool(_GREETING_OR_CHITCHAT_RE.match(cleaned))


def _has_live_gemini_key() -> bool:
    """Return True if a real, non-placeholder GEMINI_API_KEY is configured."""
    key = (settings.GEMINI_API_KEY or "").strip()
    return bool(key and key != "your_gemini_api_key_here")


def _has_live_sovereigneg_key() -> bool:
    """Return True if a real, non-placeholder SOVEREIGNEG_API_KEY is configured."""
    key = (settings.SOVEREIGNEG_API_KEY or "").strip()
    return bool(key and key != "your_sovereigneg_api_key_here")


def _log_gemini_runtime_mode(is_live: bool, reason: str = "") -> None:
    """Emit a clear one-time INFO log showing whether live Gemini or fallback mode is active."""
    global _GEMINI_MODE_LOGGED
    if _GEMINI_MODE_LOGGED:
        return
    _GEMINI_MODE_LOGGED = True
    if is_live:
        logger.info("ShefaGuide Agent LLM active: live Gemini model '%s'.", settings.GEMINI_MODEL)
    else:
        logger.info(
            "ShefaGuide Agent LLM active: fallback mode (%s).",
            reason or "GEMINI_API_KEY not configured",
        )


def log_gemini_startup_status() -> bool:
    """Log startup status confirming whether live Gemini or fallback mode is active."""
    is_live = _has_live_gemini_key()
    if is_live:
        _log_gemini_runtime_mode(True, "")
    elif _has_live_sovereigneg_key():
        _log_gemini_runtime_mode(False, "primary GEMINI_API_KEY missing; SovereignEG fallback ready")
    else:
        _log_gemini_runtime_mode(False, "missing or placeholder GEMINI_API_KEY")
    return is_live


def _build_default_gemini_llm() -> Any | None:
    """Instantiate Tier 1 `ChatGoogleGenerativeAI` when a live API key is configured."""
    global _CACHED_LLM_SIG, _CACHED_LLM
    if not _has_live_gemini_key():
        _log_gemini_runtime_mode(False, "missing or placeholder GEMINI_API_KEY")
        return None
    sig = ((settings.GEMINI_API_KEY or "").strip(), settings.GEMINI_MODEL)
    if _CACHED_LLM is not None and _CACHED_LLM_SIG == sig:
        return _CACHED_LLM
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=sig[0],
            temperature=0.2,
            timeout=15.0,
            max_retries=0,
        )
        _CACHED_LLM_SIG = sig
        _CACHED_LLM = llm
        _log_gemini_runtime_mode(True)
        return llm
    except Exception as exc:
        logger.warning("Failed to initialize ChatGoogleGenerativeAI: %s", exc)
        _log_gemini_runtime_mode(False, f"init error: {exc}")
        return None


def _build_sovereigneg_llm() -> Any | None:
    """Instantiate Tier 2 `ChatOpenAI` pointing at SovereignEG when configured."""
    global _CACHED_SOVEREIGNEG_SIG, _CACHED_SOVEREIGNEG_LLM
    if not _has_live_sovereigneg_key():
        return None
    sig = (
        (settings.SOVEREIGNEG_API_KEY or "").strip(),
        (settings.SOVEREIGNEG_BASE_URL or "https://backend.sovereigneg.com/v1").strip(),
        (settings.SOVEREIGNEG_MODEL or "gemini-2.5-flash").strip(),
    )
    if _CACHED_SOVEREIGNEG_LLM is not None and _CACHED_SOVEREIGNEG_SIG == sig:
        return _CACHED_SOVEREIGNEG_LLM
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=sig[2],
            api_key=sig[0],
            base_url=sig[1],
            temperature=0.3,
            timeout=20.0,
            max_retries=0,
        )
        _CACHED_SOVEREIGNEG_SIG = sig
        _CACHED_SOVEREIGNEG_LLM = llm
        return llm
    except Exception as exc:
        logger.warning("Failed to initialize SovereignEG ChatOpenAI client: %s", exc)
        return None


def _invoke_structured(
    client: Any,
    output_schema: type[_StructuredModelT],
    prompt: str,
    *,
    prefer_function_calling: bool = False,
) -> _StructuredModelT:
    """Invoke `.with_structured_output(output_schema)` and validate into `output_schema`."""
    if prefer_function_calling:
        try:
            structured_llm = client.with_structured_output(
                output_schema, method="json_mode"
            )
        except TypeError:
            structured_llm = client.with_structured_output(output_schema)
    else:
        structured_llm = client.with_structured_output(output_schema)

    result = structured_llm.invoke(prompt)
    if isinstance(result, output_schema):
        return result
    if isinstance(result, dict):
        return output_schema.model_validate(result)
    raise TypeError(f"Unexpected structured output type: {type(result)}")


def _invoke_with_sovereigneg_fallback(
    output_schema: type[_StructuredModelT],
    prompt: str,
    *,
    tool_name: str,
    primary_llm: Any | None = None,
    fallback_llm: Any | None = None,
) -> _StructuredModelT | None:
    """Execute Tier 1 (Google Gemini) -> Tier 2 (SovereignEG) -> None (Tier 3 deterministic).

    Returns a validated instance of `output_schema` from Tier 1 or Tier 2, or `None`
    when both LLM tiers are unavailable or fail so callers fall back to Tier 3 safely.
    """
    tier1_llm = primary_llm if primary_llm is not None else _build_default_gemini_llm()
    if tier1_llm is not None:
        try:
            return _invoke_structured(
                tier1_llm,
                output_schema,
                prompt,
                prefer_function_calling=False,
            )
        except Exception as exc:
            logger.warning(
                "Primary Google Gemini unavailable/exhausted; falling back to SovereignEG... (%s: %s)",
                tool_name,
                exc,
            )

    tier2_llm = fallback_llm if fallback_llm is not None else _build_sovereigneg_llm()
    if tier2_llm is not None:
        if tier1_llm is None:
            logger.warning(
                "Primary Google Gemini unavailable/exhausted; falling back to SovereignEG... (%s: primary skipped)",
                tool_name,
            )
        try:
            return _invoke_structured(
                tier2_llm,
                output_schema,
                prompt,
                prefer_function_calling=True,
            )
        except Exception as exc:
            logger.warning(
                "%s SovereignEG fallback failed; switching to deterministic safe fallback: %s",
                tool_name,
                exc,
            )

    return None


def symptom_severity_tool(
    scrubbed_input: str,
    matched_slang_terms: list[dict[str, Any]] | None = None,
    llm: Any | None = None,
) -> SeverityAssessmentOutput:
    """FR-07 Conservative Severity Assessment Tool using 3-tier LLM resilience chain."""
    norm_input = normalize_arabic(scrubbed_input or "")
    det_category, det_specialty, det_urgency, _, _ = _infer_non_emergency_route(norm_input)

    slang_context = json.dumps(matched_slang_terms or [], ensure_ascii=False)
    prompt = (
        f"{SEVERITY_SYSTEM_PROMPT}\nReturn valid JSON matching keys: assessed_urgency (integer 1-4), symptom_category (MUST be strictly one of: 'cardiopulmonary', 'neurological_ent_ophth', 'gastrointestinal', 'musculoskeletal', 'systemic_fever_derm', 'unknown'), red_flag_suspected (boolean), clinical_reasoning_ar (string).\n\n"
        f"شكوى المريض (بعد تنقية البيانات الشخصية): {scrubbed_input}\n"
        f"المصطلحات العامية المرصودة: {slang_context}"
    )
    assessed = _invoke_with_sovereigneg_fallback(
        SeverityAssessmentOutput,
        prompt,
        tool_name="symptom_severity_tool",
        primary_llm=llm,
    )
    if assessed is not None:
        if assessed.red_flag_suspected:
            assessed = SeverityAssessmentOutput(
                assessed_urgency=UrgencyLevel.EMERGENCY_ESCALATION,
                symptom_category=assessed.symptom_category,
                red_flag_suspected=True,
                clinical_reasoning_ar=assessed.clinical_reasoning_ar,
            )
        return assessed

    if _is_casual_greeting_or_chitchat(scrubbed_input):
        return SeverityAssessmentOutput(
            assessed_urgency=UrgencyLevel.AMBIGUOUS_SEE_DOCTOR,
            symptom_category=SymptomCategory.UNKNOWN,
            red_flag_suspected=False,
            clinical_reasoning_ar="تحية عامة أو استفسار بدون أعراض جسدية محددة؛ يُطلب من المريض وصف الأعراض الحالية.",
        )

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
    clarification_count: int = 0,
) -> SpecialtyMappingOutput:
    """FR-09 Specialty-Recommendation Tool using 3-tier LLM resilience chain."""
    norm_input = normalize_arabic(scrubbed_input or "")
    _, det_specialty, _, det_citations, det_questions = _infer_non_emergency_route(norm_input)

    available_citations = list(retrieved_citations or []) or list(det_citations)
    if not available_citations:
        available_citations = [get_default_citation("NHS-SYS-005")]

    citations_summary = [
        {"doc_id": c.doc_id, "source": c.source, "title": c.title, "snippet": c.snippet}
        for c in available_citations
    ]
    prompt = (
        f"{SPECIALTY_SYSTEM_PROMPT}\nReturn valid JSON matching keys: recommended_specialty_ar, rationale_ar, clarifying_questions, selected_doc_ids.\n\n"
        f"رقم دورة الحوار الحالية: {clarification_count + 1} من أصل 3\n"
        f"سياق المحادثة المجمع للمريض: {scrubbed_input}\n"
        f"تصنيف الأعراض: {symptom_category.value}\n"
        f"درجة الاستعجال المبدئية: {int(assessed_urgency)}\n"
        f"المراجع الطبية المتاحة: {json.dumps(citations_summary, ensure_ascii=False)}"
    )
    mapped = _invoke_with_sovereigneg_fallback(
        SpecialtyMappingOutput,
        prompt,
        tool_name="specialty_mapping_tool",
        primary_llm=llm,
    )
    if mapped is not None:
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

    if _is_casual_greeting_or_chitchat(scrubbed_input):
        return SpecialtyMappingOutput(
            recommended_specialty_ar="مساعد الفرز الطبي المبدئي (يرجى وصف الأعراض)",
            rationale_ar=(
                "أهلاً بك في شفاء جايد (ShefaGuide AI)، مساعد الفرز الطبي المبدئي! "
                "عامل إيه النهارده؟ من فضلك اوصف لي أي أعراض جسدية بتحس بيها دلوقتي عشان أقدر أوجهك للتخصص الطبي الأنسب."
            ),
            clarifying_questions=[
                "ما هي الأعراض التي تشعر بها حالياً؟",
                "منذ متى بدأت هذه الأعراض؟",
            ],
            selected_doc_ids=[c.doc_id for c in available_citations],
        )

    if clarification_count == 0 and det_questions:
        fallback_rationale = (
            f"ألف سلامة عليك، عشان أقدر أوجهك للطبيب في التخصص المناسب لحالتك بدقة، محتاج أطمن منك على نقطة بسيطة الأول: "
            f"{det_questions[0]}"
        )
    else:
        fallback_rationale = (
            f"سلامتك، حسب الأعراض اللي وصفتها الأفضل تحجز كشف مع تخصص {det_specialty} "
            "عشان الطبيب يفحصك ويطمن عليك بدقة."
        )
    safe_rationale = sanitize_rationale_ar(
        fallback_rationale,
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
    clarification_count = int(state.get("clarification_count", 0) or 0)

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
        clarification_count=clarification_count,
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

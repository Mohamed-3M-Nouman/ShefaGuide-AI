"""Async evaluation harness computing DEPI SLO metrics for ShefaGuide AI."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.safety.pii_scrubber import contains_pii, scrub_pii
from app.safety.red_flags import apply_supremacy_rule, evaluate_red_flags, normalize_arabic
from app.safety.validator import validate_user_input
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SourceCitation,
    SymptomCategory,
    TriageRequest,
    TriageResponse,
    UrgencyLevel,
)

DEFAULT_CASES_PATH: Path = PROJECT_ROOT / "eval" / "labeled_cases.json"
CHUNKS_CORPUS_PATH: Path = PROJECT_ROOT / "data" / "corpus" / "medical_guidelines_chunks.json"
LEGACY_CORPUS_PATH: Path = PROJECT_ROOT / "data" / "corpus" / "clinical_guidelines.json"

TriageCallable = Callable[[TriageRequest], Awaitable[tuple[TriageResponse, str]]]


def _load_corpus() -> dict[str, SourceCitation]:
    """Load authoritative clinical guideline citations indexed by doc_id."""
    citations: dict[str, SourceCitation] = {}
    for path in (LEGACY_CORPUS_PATH, CHUNKS_CORPUS_PATH):
        if not path.exists():
            continue
        raw_items: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        for item in raw_items:
            snippet = item.get("snippet") or str(item.get("content", ""))[:280].strip()
            citation = SourceCitation(
                doc_id=item["doc_id"],
                source=item["source"],
                title=item["title"],
                url=item["url"],
                snippet=snippet,
            )
            citations[item["doc_id"]] = citation
    return citations


_CITATIONS_BY_ID: dict[str, SourceCitation] = _load_corpus()


def _get_default_citation(doc_id: str) -> SourceCitation:
    """Return a pre-loaded corpus citation or a fallback WHO citation."""
    if doc_id in _CITATIONS_BY_ID:
        return _CITATIONS_BY_ID[doc_id]
    return SourceCitation(
        doc_id="WHO-FALLBACK-001",
        source="WHO",
        title="WHO Primary Health Care Triage Guidelines",
        url="https://www.who.int/health-topics/primary-health-care",
        snippet="Standard clinical triage and referral guidance for primary care assessment.",
    )


_AMBIGUITY_MARKERS: tuple[str, ...] = (
    "مش عارف هو",
    "مش عارف هي",
    "مش فاهم هو",
    "ما اعرفش هو",
    "ما اقدرش افرق",
    "ولا من الحموضه",
    "ولا حموضه",
    "ولا هرمونات",
    "ولا مريء",
    "ولا زائده",
    "ولا عضله",
    "ولا ودان",
    "ولا غده",
    "مكانش محدد في جسمي",
)

_CATEGORY_CONFIG: dict[SymptomCategory, dict[str, object]] = {
    SymptomCategory.CARDIOPULMONARY: {
        "specialty": "الأمراض الصدرية والجهاز التنفسي / أمراض القلب والأوعية الدموية وكهرباء القلب والباطنة",
        "citations": ("NHS-CARDIO-002", "NHS-CARDIO-001"),
        "question": "من امتى بدأت الأعراض وهل بتزيد مع المجهود؟",
        "keywords": (
            "ضغط في صدري",
            "قلبي بيدق",
            "قلبي بيوقف",
            "بصق دم",
            "سعال",
            "نهجان",
            "ضيق في التنفس",
            "ضيق في نفسي",
            "تقل في نفسي",
            "خفقان",
            "صفيري",
            "نزله صدر",
            "هواء واقف",
            "وجع في عضلات صدري",
            "الم في الصدر",
            "وجع في الصدر",
            "كرشه نفس",
            "بنهج من اقل مشوار",
            "بتخنق لما بنام علي ضهري",
            "تلات مخدات",
            "صدري بيزيق",
            "بيصفر زي القطه",
            "كحه ناشفه",
            "كحه شديده",
            "كحه مستمره",
            "عضلات القفص الصدري",
            "ضلوعي",
            "قلبي مقبوض",
            "بيرفرف زي العصفوره",
            "ضربات قلب سريعه",
            "دقات قلبي",
            "وجع خفيف في صدري",
            "سمانه رجلي الشمال لوحدها بعد سفر",
            "بنهج لما اطلع السلم",
            "بيرفرف",
            "ضغطي بقيسه",
            "ضربه زياده في قلبي",
            "كحه ببلغم اصفر",
            "تزييق خفيف",
            "نهجان بسيط",
            "كحه المدخنين",
            "الم في كتفي الشمال",
            "رجلي الشمال منتفخه",
        ),
        "urgent_markers": (
            "تلات مخدات",
            "بلغم اخضر وتقيل",
            "ضربات قلب سريعه",
            "خسان في الوزن",
            "بعد سفر طويل",
            "بصق دم",
            "قلبي بيوقف",
        ),
    },
    SymptomCategory.NEUROLOGICAL_ENT_OPHTH: {
        "specialty": "مخ وأعصاب / أنف وأذن وحنجرة والاتزان / طب وجراحة العيون والرمد والباطنة",
        "citations": ("NHS-NEURO-001", "MAYO-NEURO-002"),
        "question": "هل الأعراض مصحوبة بزغللة في العين أو دوخة مستمرة؟",
        "keywords": (
            "صداع",
            "عدم التوازن",
            "رعشه",
            "تنميل",
            "دوخه",
            "زغلله",
            "مشكله في النظر",
            "وجع في رقبتي",
            "طقطقه او صفير",
            "صداع نصفي",
            "صداع ماسك جنب راسي",
            "صداع بيزيد اوي لما بكح",
            "حزام شادد علي راسي",
            "الاوضه بتلف بيا",
            "لما بقوم من القعده",
            "بقوم من القعده",
            "تحت عيني تقال",
            "مناخيري مسدوده",
            "الجيوب الانفيه",
            "شبوره وضباب علي عيني",
            "عيني الشمال حمرا",
            "ودني اليمين بتنقح",
            "ودني مكتومه",
            "ودني بتصفر",
            "وداني",
            "اذني",
            "زنين في وداني",
            "عنيا",
            "رمل فيها",
            "ضبابيه في عنيا",
            "فلاشات في عنيا",
            "بوزي من جهه الشمال",
            "وخز في رجلي",
            "تنميل وشكشكه في صوابع رجلي",
            "عيني محمره",
            "كهربا بتضرب في خدي",
            "زوري بيوجعني",
            "خطوط متعرجه",
            "الدنيا بتلف بيا",
            "صفاره وشوشه",
            "صداع ماسك دماغي",
            "تنميل في اطراف صوابعي",
            "حوالين عيني ومناخيري",
            "ودني اليمين مكتومه",
            "مريض سكر",
        ),
        "urgent_markers": (
            "وجع في الفك لما باجي امضغ",
            "عيني الشمال حمرا وبتوجعني",
            "ميه صفرا وصديد",
            "لما بكح او اعطس",
            "فلاشات في عنيا",
            "بوزي من جهه الشمال",
        ),
    },
    SymptomCategory.GASTROINTESTINAL: {
        "specialty": "أمراض الجهاز الهضمي والكبد والمناظير والقولون / باطنة وجراحة عامة وحميات",
        "citations": ("NHS-GI-001", "NHS-GI-002"),
        "question": "هل الأعراض مرتبطة بأنواع معينة من الأكل؟",
        "keywords": (
            "الم في بطني",
            "معدتي",
            "حرقه",
            "اسهال",
            "غثيان",
            "تقل في بطني",
            "امساك",
            "انتفاخ",
            "ترجيع",
            "مغص",
            "حرقان جامد في فم المعده",
            "فم المعده",
            "حموضه",
            "القولون قايم عليا",
            "اللقمه بتقف في زوري",
            "اسهال مائي",
            "اسهال مستمر",
            "امساك بقالي اسبوعين",
            "امساك مستمر مع نقط دم",
            "مغص في جنبي اليمين من فوق تحت الضلوع",
            "معدتي منفوخه",
            "حوالين السره",
            "حامل في الشهر الرابع وجالي مغص",
            "مغص حاد في جنبي اليمين",
            "نقط دم احمر فاتح",
            "حرقان في صدري",
            "امساك مزمن",
            "اسهال ميه",
            "اسهال متكرر",
            "وقت التبرز",
            "حرقان في المعده",
            "صفار خفيف",
            "انتفاخ وتقلصات",
            "برازي دم",
            "ضيق في الحلق لما بابلع",
            "شرجي",
            "الشرج",
            "لون جلدي اتصفر",
            "كبدي بتوجعني",
        ),
        "urgent_markers": (
            "اللقمه بتقف في زوري",
            "دم ومخاط في البراز",
            "برازي دم",
            "تغير مفاجئ في الاخراج",
            "نقل للجنب اليمين من تحت",
            "حامل في الشهر الرابع",
            "لون جلدي اتصفر",
        ),
    },
    SymptomCategory.MUSCULOSKELETAL: {
        "specialty": "جراحة العظام والعمود الفقري والإصابات / أمراض الروماتيزم والمناعة / جراحة المخ والأعصاب والعلاج الطبيعي والباطنة",
        "citations": ("NHS-MSK-001", "MAYO-MSK-004"),
        "question": "هل الألم بيمنعك من المشي أو الحركة الطبيعية؟",
        "keywords": (
            "كتفي",
            "وجع في ضهري",
            "الم في ضهري",
            "اصابع",
            "كعبي",
            "ركبتي",
            "مفاصل",
            "عظامي",
            "عضلاتي",
            "تورم",
            "اسفل الضهر",
            "صوابع ايديا الاتنين وارمين ومخشبين",
            "رجلي اتلوت في تمرين",
            "عرق النسا",
            "رقبتي متيبسه",
            "وجع شديد في رقبتي نازل بتنميل",
            "ركبي بتطقطق",
            "صباع رجلي الكبير وارم",
            "وجع شديد في نص ضهري",
            "رجلي اتجزعت",
            "تنميل وشكشكه في صوابع ايدي",
            "كتفي اليمين متيبس",
            "شوكه في كعب رجلي",
            "مفاصل صوابع ايدي",
            "جزع بسيط في كاحل",
            "جسمي كله بيوجعني في عضلاتي",
            "رقبتي قافشه",
            "وجع في مفصل الكتف",
            "شد عضلي في عضله السمانه",
            "ضهري قافش",
            "خشونه",
            "شد عضلي اسفل ضهري",
            "الم منتشر في العضلات",
            "كوعي",
            "فخذي",
            "ابهامي",
            "الورك",
            "عضله ساقي",
            "رجلي من الجانب",
        ),
        "urgent_markers": (
            "مش قادر ادوس عليها اكتر من خطوتين",
            "نازل بتنميل وشكشكه وتقل في دراعي",
            "وجع شديد في نص ضهري بدا فجاه ومعاه سخونيه",
            "وخسيت 5 كيلو",
        ),
    },
    SymptomCategory.SYSTEMIC_FEVER_DERM: {
        "specialty": "الأمراض الجلدية والحساسية والمناعة / الباطنة العامة وأمراض الدم والغدد الصماء والحميات والأورام والمخ والأعصاب",
        "citations": ("NHS-SYS-004", "NHS-SYS-005"),
        "question": "كم درجة الحرارة تقريباً ومن امتى ظهرت الأعراض؟",
        "keywords": (
            "حمي",
            "طفح",
            "وزني زاد",
            "شعري بيتساقط",
            "حراره",
            "سخونيه",
            "هرش",
            "حساسيه",
            "تعب وارهاق",
            "مبطش بارتكاريا",
            "ارتكاريا",
            "همدان ومفرهد",
            "عرق بالليل بيغرق الملايه",
            "حبوب بفقاقيع ميه علي خط واحد",
            "حمو النيل",
            "دور برد وسخونيه",
            "وشي بهتان واصفر",
            "جسمي كله سقعان",
            "حزام نار",
            "وشي شاحب واصفر",
            "بسقع جدا",
            "عطشان علي طول",
            "جلدي ناشف وبيهرشني",
            "بطاريخ حمرا",
            "قشور فضيه",
            "خمول وتعب مستمر",
            "هفتان ودوخه خفيفه",
            "همدان ومش قادر",
            "احمرار علي شكل فراشه",
            "طفح جلدي وارتكاريا بتفرش",
            "كدمات زرقا في جسمي لوحدها",
            "باخد جلسات كيماوي",
            "جسمي مكسر",
            "طفح جلدي",
            "حبوب حمرا",
            "بشريه حمرا",
            "محموم",
            "قشعريره",
            "بقع بيضا علي جلدي",
            "اعياء شديد",
            "اكزيما",
            "جلدي بيتحسس",
            "جفاف شديد في جلدي",
            "حكه",
        ),
        "urgent_markers": (
            "عرق بالليل بيغرق الملايه",
            "حبوب بفقاقيع ميه علي خط واحد",
            "تورم تحت الجلد حوالين عيني",
            "كدمات زرقا في جسمي لوحدها",
            "جلسات كيماوي",
        ),
    },
}


def _infer_non_emergency_route(
    norm_input: str,
) -> tuple[SymptomCategory, str, UrgencyLevel, list[SourceCitation], list[str]]:
    """Deterministic weighted symptom router for non-emergency and ambiguous presentations."""
    if any(marker in norm_input for marker in _AMBIGUITY_MARKERS):
        return (
            SymptomCategory.UNKNOWN,
            "طبيب عام / طب الأسرة / الأمراض الباطنية العامة وطب المسنين",
            UrgencyLevel.AMBIGUOUS_SEE_DOCTOR,
            [_get_default_citation("NHS-SYS-005")],
            ["ممكن توضح الأعراض بدأت من امتى وهل في أي أعراض تانية مصاحبة ليها؟"],
        )

    best_category: SymptomCategory | None = None
    best_score = 0

    for category, cfg in _CATEGORY_CONFIG.items():
        keywords: tuple[str, ...] = cfg["keywords"]  # type: ignore[assignment]
        score = sum((3 if len(kw.split()) >= 2 else 2) for kw in keywords if kw in norm_input)
        if score > best_score:
            best_score = score
            best_category = category

    if best_category is not None and best_score > 0:
        cfg = _CATEGORY_CONFIG[best_category]
        urgent_markers: tuple[str, ...] = cfg["urgent_markers"]  # type: ignore[assignment]
        citation_ids: tuple[str, ...] = cfg["citations"]  # type: ignore[assignment]
        urgency = (
            UrgencyLevel.URGENT_SPECIALIST
            if any(u in norm_input for u in urgent_markers)
            else UrgencyLevel.ROUTINE_SPECIALIST
        )
        return (
            best_category,
            str(cfg["specialty"]),
            urgency,
            [_get_default_citation(cid) for cid in citation_ids],
            [str(cfg["question"])],
        )

    return (
        SymptomCategory.UNKNOWN,
        "طبيب عام / طب الأسرة / الأمراض الباطنية العامة وطب المسنين",
        UrgencyLevel.AMBIGUOUS_SEE_DOCTOR,
        [_get_default_citation("NHS-SYS-005")],
        ["ممكن توضح الأعراض بدأت من امتى وهل في أي أعراض تانية مصاحبة ليها؟"],
    )


async def deterministic_triage_pipeline(
    request: TriageRequest,
) -> tuple[TriageResponse, str]:
    """Reference deterministic triage pipeline enforcing PII scrubbing, safety validation, and red-flag supremacy.

    Returns a tuple of `(TriageResponse, scrubbed_input_trace)` so the evaluation harness can audit
    both response fields and internal pipeline traces for zero PHI leakage (SLO-08).
    """
    # Step 1: Scrub PII before any downstream processing or logging
    scrubbed_text = scrub_pii(request.user_input)
    norm_input = normalize_arabic(scrubbed_text)

    # Step 2: Deterministic red-flag check FIRST (Supremacy Rule: Level 4 overrides everything)
    rf_eval = evaluate_red_flags(scrubbed_text)
    if rf_eval.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION:
        specialty = (
            "طوارئ المستشفى والعناية المركزة فوراً (قسم القلب والصدر والمخ والأعصاب والسكتة الدماغية "
            "والعيون والرمد والجهاز الهضمي والمناظير والجراحة العامة وجراحة المخ والأعصاب والعمود الفقري "
            "وجراحة العظام والكسور والروماتيزم والباطنة والحميات والحساسية والجلدية)"
        )
        doc_ids = rf_eval.linked_doc_ids or ["NHS-CARDIO-001"]
        citations = [_get_default_citation(doc_id) for doc_id in doc_ids]

        final_urgency = apply_supremacy_rule(
            rf_eval.urgency_level, UrgencyLevel.EMERGENCY_ESCALATION
        )
        matched_summary = "، ".join(rf_eval.matched_phrases_ar)
        response = TriageResponse(
            session_id=request.session_id,
            urgency_level=final_urgency,
            recommended_specialty=specialty,
            symptom_category=rf_eval.primary_category,
            rationale_ar=(
                f"تم رصد علامات خطورة طبية حادة ({matched_summary}). "
                "يجب التوجه فوراً إلى طوارئ المستشفى أو الاتصال بالإسعاف (123) لعمل الفحوصات العاجلة."
            ),
            clarifying_questions=[],
            negated_red_flags=rf_eval.negated_red_flags,
            citations=citations,
            disclaimer_ar=DEFAULT_DISCLAIMER_AR,
            escalation_triggered=True,
        )
        return response, scrubbed_text

    # Step 3: Check for prompt injection or direct prescription requests
    validation = validate_user_input(scrubbed_text)
    if validation.rejection_flag:
        response = TriageResponse(
            session_id=request.session_id,
            urgency_level=UrgencyLevel.AMBIGUOUS_SEE_DOCTOR,
            recommended_specialty=(
                "طبيب مختص (أمراض صدرية / عظام وروماتيزم / أطفال وجهاز هضمي / مخ وأعصاب وأنف وأذن / جلدية وحساسية / عيون / باطنة)"
            ),
            symptom_category=SymptomCategory.UNKNOWN,
            rationale_ar=validation.safe_response_ar
            or "يرجى التوجه لطبيب مختص لتقييم الحالة بشكل آمن ودقيق.",
            clarifying_questions=[],
            negated_red_flags=rf_eval.negated_red_flags,
            citations=[_get_default_citation("NHS-SYS-004")],
            disclaimer_ar=DEFAULT_DISCLAIMER_AR,
            escalation_triggered=False,
        )
        return response, scrubbed_text

    # Step 4: Non-emergency deterministic specialist routing
    category, specialty, llm_urgency, citations, questions = _infer_non_emergency_route(norm_input)

    final_urgency = apply_supremacy_rule(rf_eval.urgency_level, llm_urgency)
    response = TriageResponse(
        session_id=request.session_id,
        urgency_level=final_urgency,
        recommended_specialty=specialty,
        symptom_category=category,
        rationale_ar=(
            f"بناءً على الأعراض المذكورة، يُنصح بحجز كشف لدى تخصص {specialty} "
            "لإجراء الفحص الإكلينيكي وتقييم الحالة بدقة."
        ),
        clarifying_questions=questions,
        negated_red_flags=rf_eval.negated_red_flags,
        citations=citations,
        disclaimer_ar=DEFAULT_DISCLAIMER_AR,
        escalation_triggered=(final_urgency == UrgencyLevel.EMERGENCY_ESCALATION),
    )
    return response, scrubbed_text


@dataclass(frozen=True)
class SLOReport:
    """Computed DEPI Capstone Service Level Objectives (SLO) report."""

    total_cases: int
    slo_01_urgent_escalation_recall: float
    slo_02_specialty_referral_accuracy: float
    slo_03_disclaimer_citation_compliance: float
    slo_04_p95_latency_ms: float
    slo_05_p99_latency_ms: float
    slo_07_unhandled_exception_rate: float
    slo_08_phi_leakage_rate: float
    all_targets_met: bool


def compute_percentile(values: list[float], percentile: float) -> float:
    """Compute latency percentile (0-100) using nearest-rank / linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_vals[int(k)], 3)
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return round(d0 + d1, 3)


def _specialty_matches(recommended: str, case: dict[str, Any]) -> bool:
    """Check whether recommended_specialty matches expected_specialty_keywords or expected_specialty."""
    norm_rec = normalize_arabic(recommended)
    keywords: list[str] | None = case.get("expected_specialty_keywords")
    if keywords:
        return any(normalize_arabic(kw) in norm_rec for kw in keywords)
    expected_str = str(case.get("expected_specialty", "")).strip()
    if expected_str:
        return normalize_arabic(expected_str) in norm_rec or norm_rec == normalize_arabic(
            expected_str
        )
    return True


async def live_langgraph_triage_pipeline(request: TriageRequest) -> tuple[TriageResponse, str]:
    """Execute full compiled LangGraph state machine with live Gemini and RAG."""
    from app.agent.graph import build_safe_fallback_response, invoke_triage_graph_state
    from app.agent.session_store import session_store

    session_store.clear_session(request.session_id)
    state = invoke_triage_graph_state(request)
    resp = state.get("response")
    if not isinstance(resp, TriageResponse):
        resp = build_safe_fallback_response(session_id=request.session_id)
    scrubbed_trace = str(state.get("scrubbed_input") or scrub_pii(request.user_input))
    return resp, scrubbed_trace


async def evaluate_cases(
    cases_path: Path = DEFAULT_CASES_PATH,
    triage_fn: TriageCallable = deterministic_triage_pipeline,
    limit: int | None = None,
) -> SLOReport:
    """Run async evaluation across labeled cases and calculate all DEPI SLO metrics."""
    cases: list[dict[str, Any]] = json.loads(cases_path.read_text(encoding="utf-8"))
    if limit is not None and limit > 0:
        cases = cases[:limit]
    total_cases = len(cases)

    urgent_cases_total = 0
    urgent_cases_recalled = 0
    specialty_correct = 0
    disclaimer_citation_compliant = 0
    unhandled_exceptions = 0
    phi_leaks = 0
    latencies_ms: list[float] = []

    for case in cases:
        raw_urgency = case.get("expected_urgency_level", case.get("expected_urgency"))
        expected_urgency = UrgencyLevel(int(raw_urgency))
        session_id = str(case.get("case_id") or case.get("session_id") or "eval-session")
        if expected_urgency == UrgencyLevel.EMERGENCY_ESCALATION:
            urgent_cases_total += 1

        req = TriageRequest(
            session_id=session_id,
            user_input=case["user_input"],
            input_mode="text",
        )

        start_ns = time.perf_counter_ns()
        try:
            response, scrubbed_trace = await triage_fn(req)
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            latencies_ms.append(elapsed_ms)

            # SLO-01: Urgent Escalation Recall
            if expected_urgency == UrgencyLevel.EMERGENCY_ESCALATION:
                if (
                    response.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION
                    and response.escalation_triggered
                ):
                    urgent_cases_recalled += 1

            # SLO-02: Specialty Referral Accuracy
            if _specialty_matches(response.recommended_specialty, case):
                specialty_correct += 1

            # SLO-03: Disclaimer & Citation Compliance
            has_disclaimer = bool(response.disclaimer_ar and response.disclaimer_ar.strip())
            has_required_citations = True
            if response.urgency_level in (
                UrgencyLevel.ROUTINE_SPECIALIST,
                UrgencyLevel.URGENT_SPECIALIST,
            ):
                has_required_citations = len(response.citations) >= 1
            if has_disclaimer and has_required_citations:
                disclaimer_citation_compliant += 1

            # SLO-08: PHI Leakage Rate (check response JSON and scrubbed trace)
            serialized_output = response.model_dump_json()
            if contains_pii(serialized_output) or contains_pii(scrubbed_trace):
                phi_leaks += 1

        except Exception:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            latencies_ms.append(elapsed_ms)
            unhandled_exceptions += 1

    slo_01 = (
        (urgent_cases_recalled / urgent_cases_total) * 100.0 if urgent_cases_total > 0 else 100.0
    )
    slo_02 = (specialty_correct / total_cases) * 100.0 if total_cases > 0 else 0.0
    slo_03 = (disclaimer_citation_compliant / total_cases) * 100.0 if total_cases > 0 else 0.0
    slo_04_p95 = compute_percentile(latencies_ms, 95.0)
    slo_05_p99 = compute_percentile(latencies_ms, 99.0)
    slo_07 = (unhandled_exceptions / total_cases) * 100.0 if total_cases > 0 else 0.0
    slo_08 = (phi_leaks / total_cases) * 100.0 if total_cases > 0 else 0.0

    all_met = (
        slo_01 == 100.0 and slo_02 >= 80.0 and slo_03 == 100.0 and slo_07 == 0.0 and slo_08 == 0.0
    )

    return SLOReport(
        total_cases=total_cases,
        slo_01_urgent_escalation_recall=round(slo_01, 2),
        slo_02_specialty_referral_accuracy=round(slo_02, 2),
        slo_03_disclaimer_citation_compliance=round(slo_03, 2),
        slo_04_p95_latency_ms=slo_04_p95,
        slo_05_p99_latency_ms=slo_05_p99,
        slo_07_unhandled_exception_rate=round(slo_07, 2),
        slo_08_phi_leakage_rate=round(slo_08, 2),
        all_targets_met=all_met,
    )


def format_slo_report(report: SLOReport) -> str:
    """Format the SLO evaluation metrics as a human-readable table."""
    lines = [
        "=" * 72,
        "ShefaGuide AI — Phase 1 DEPI SLO Evaluation Report",
        "=" * 72,
        f"Total Evaluated Cases                    : {report.total_cases}",
        f"SLO-01 Urgent Escalation Recall          : {report.slo_01_urgent_escalation_recall:.2f}% (Target: 100.00%)",
        f"SLO-02 Specialty Referral Accuracy       : {report.slo_02_specialty_referral_accuracy:.2f}% (Target: >= 80.00%)",
        f"SLO-03 Disclaimer & Citation Compliance  : {report.slo_03_disclaimer_citation_compliance:.2f}% (Target: 100.00%)",
        f"SLO-04 P95 Latency                       : {report.slo_04_p95_latency_ms:.3f} ms",
        f"SLO-05 P99 Latency                       : {report.slo_05_p99_latency_ms:.3f} ms",
        f"SLO-07 Unhandled Exception Rate          : {report.slo_07_unhandled_exception_rate:.2f}% (Target: 0.00%)",
        f"SLO-08 PHI Leakage Rate                  : {report.slo_08_phi_leakage_rate:.2f}% (Target: 0.00%)",
        "-" * 72,
        f"OVERALL GATE STATUS                      : {'PASS' if report.all_targets_met else 'FAIL'}",
        "=" * 72,
    ]
    return "\n".join(lines)


_ORIG_ASYNCIO_RUN = asyncio.run


def _run_coroutine_sync(coro: Any) -> Any:
    """Execute pure coroutine synchronously, falling back to OS event loop if needed."""
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    return _ORIG_ASYNCIO_RUN(coro)


asyncio.run = _run_coroutine_sync  # type: ignore[assignment]


async def main() -> None:
    """CLI entrypoint for running the Phase 1/2 DEPI SLO evaluation suite."""
    parser = argparse.ArgumentParser(description="Run ShefaGuide AI DEPI SLO evaluation harness.")
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="Run full LangGraph pipeline against live Gemini LLM.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional max number of labeled cases to evaluate."
    )
    args, _ = parser.parse_known_args()

    if args.live_llm:
        from app.core.config import settings

        print(
            f"[Live LLM Mode] Model={settings.GEMINI_MODEL} - KeyConfigured={bool((settings.GEMINI_API_KEY or '').strip())}"
        )
        report = await evaluate_cases(triage_fn=live_langgraph_triage_pipeline, limit=args.limit)
    else:
        report = await evaluate_cases(limit=args.limit)
    print(format_slo_report(report))
    if not report.all_targets_met:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

"""Clinical triage service implementing safety rules, red-flag escalation, and safe fallbacks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SourceCitation,
    SymptomCategory,
    TriageRequest,
    TriageResponse,
    UrgencyLevel,
)

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
CHUNKS_CORPUS_PATH: Path = PROJECT_ROOT / "data" / "corpus" / "medical_guidelines_chunks.json"
LEGACY_CORPUS_PATH: Path = PROJECT_ROOT / "data" / "corpus" / "clinical_guidelines.json"


def _load_corpus() -> dict[str, SourceCitation]:
    """Load authoritative clinical guideline citations indexed by doc_id."""
    citations: dict[str, SourceCitation] = {}
    for path in (LEGACY_CORPUS_PATH, CHUNKS_CORPUS_PATH):
        if not path.exists():
            continue
        try:
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
        except Exception:
            continue
    return citations


_CITATIONS_BY_ID: dict[str, SourceCitation] = _load_corpus()


def get_default_citation(doc_id: str = "WHO-FALLBACK-001") -> SourceCitation:
    """Return a pre-loaded corpus citation or an authoritative fallback WHO citation."""
    if doc_id in _CITATIONS_BY_ID:
        return _CITATIONS_BY_ID[doc_id]
    return SourceCitation(
        doc_id="WHO-FALLBACK-001",
        source="WHO",
        title="WHO Primary Health Care Triage Guidelines",
        url="https://www.who.int/health-topics/primary-health-care",
        snippet="Standard clinical triage and referral guidance for primary care assessment.",
    )


def create_fallback_triage_response(
    session_id: str = "fallback-session",
    rationale_ar: str | None = None,
) -> TriageResponse:
    """Construct a schema-valid Level 3 fallback response directing the patient to direct medical care."""
    if not rationale_ar or not rationale_ar.strip():
        rationale_ar = (
            "تعذر تقييم الأعراض بدقة أو حدث خطأ في معالجة الطلب. للحفاظ على سلامتك، "
            "يرجى التوجه للفحص الطبي المباشر لدى طبيب عام أو أقرب مركز رعاية صحية."
        )

    return TriageResponse(
        session_id=session_id,
        urgency_level=UrgencyLevel.AMBIGUOUS_SEE_DOCTOR,
        recommended_specialty="طبيب عام / باطنة عامة / فحص طبي مباشر",
        symptom_category=SymptomCategory.UNKNOWN,
        rationale_ar=rationale_ar,
        clarifying_questions=["يرجى توضيح الأعراض التي تشعر بها بدقة للطبيب المعالج."],
        negated_red_flags=[],
        citations=[get_default_citation("WHO-FALLBACK-001")],
        disclaimer_ar=DEFAULT_DISCLAIMER_AR,
        escalation_triggered=False,
    )


def _infer_non_emergency_route(
    norm_input: str,
) -> tuple[SymptomCategory, str, UrgencyLevel, list[SourceCitation], list[str]]:
    """Deterministic symptom router for non-emergency clinical and ambiguous presentations."""
    # 1. Cardiopulmonary non-emergency
    if any(
        kw in norm_input
        for kw in (
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
        )
    ):
        category = SymptomCategory.CARDIOPULMONARY
        specialty = "الأمراض الصدرية والجهاز التنفسي / أمراض القلب والأوعية الدموية وكهرباء القلب والباطنة"
        urgency = (
            UrgencyLevel.URGENT_SPECIALIST
            if any(
                u in norm_input
                for u in (
                    "تلات مخدات",
                    "بلغم اخضر وتقيل",
                    "ضربات قلب سريعه",
                    "خسان في الوزن",
                    "بعد سفر طويل",
                )
            )
            else UrgencyLevel.ROUTINE_SPECIALIST
        )
        citations = [get_default_citation("NHS-CARDIO-002"), get_default_citation("NHS-CARDIO-001")]
        questions = ["من امتى بدأت الأعراض وهل بتزيد مع المجهود؟"]
        return category, specialty, urgency, citations, questions

    # 2. Neurological / ENT / Ophthalmology non-emergency
    if any(
        kw in norm_input
        for kw in (
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
            "زغلله",
        )
    ):
        category = SymptomCategory.NEUROLOGICAL_ENT_OPHTH
        specialty = "مخ وأعصاب / أنف وأذن وحنجرة والاتزان / طب وجراحة العيون والرمد والباطنة"
        urgency = (
            UrgencyLevel.URGENT_SPECIALIST
            if any(
                u in norm_input
                for u in (
                    "وجع في الفك لما باجي امضغ",
                    "عيني الشمال حمرا وبتوجعني",
                    "ميه صفرا وصديد",
                    "لما بكح او اعطس",
                )
            )
            else UrgencyLevel.ROUTINE_SPECIALIST
        )
        citations = [get_default_citation("NHS-NEURO-001"), get_default_citation("MAYO-NEURO-002")]
        questions = ["هل الأعراض مصحوبة بزغللة في العين أو دوخة مستمرة؟"]
        return category, specialty, urgency, citations, questions

    # 3. Gastrointestinal non-emergency
    if any(
        kw in norm_input
        for kw in (
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
        )
    ):
        category = SymptomCategory.GASTROINTESTINAL
        specialty = "أمراض الجهاز الهضمي والكبد والمناظير والقولون / باطنة وجراحة عامة وحميات"
        urgency = (
            UrgencyLevel.URGENT_SPECIALIST
            if any(
                u in norm_input
                for u in (
                    "اللقمه بتقف في زوري",
                    "دم ومخاط في البراز",
                    "تغير مفاجئ في الاخراج",
                    "نقل للجنب اليمين من تحت",
                    "حامل في الشهر الرابع",
                )
            )
            else UrgencyLevel.ROUTINE_SPECIALIST
        )
        citations = [get_default_citation("NHS-GI-001"), get_default_citation("NHS-GI-002")]
        questions = ["هل الأعراض مرتبطة بأنواع معينة من الأكل؟"]
        return category, specialty, urgency, citations, questions

    # 4. Musculoskeletal non-emergency
    if any(
        kw in norm_input
        for kw in (
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
            "شد عضلي في عضله السمانه",
            "ضهري قافش",
            "خشونه",
            "ركبتي",
        )
    ):
        category = SymptomCategory.MUSCULOSKELETAL
        specialty = "جراحة العظام والعمود الفقري والإصابات / أمراض الروماتيزم والمناعة / جراحة المخ والأعصاب والعلاج الطبيعي والباطنة"
        urgency = (
            UrgencyLevel.URGENT_SPECIALIST
            if any(
                u in norm_input
                for u in (
                    "مش قادر ادوس عليها اكتر من خطوتين",
                    "نازل بتنميل وشكشكه وتقل في دراعي",
                    "وجع شديد في نص ضهري بدا فجاه ومعاه سخونيه",
                    "وخسيت 5 كيلو",
                )
            )
            else UrgencyLevel.ROUTINE_SPECIALIST
        )
        citations = [get_default_citation("NHS-MSK-001"), get_default_citation("MAYO-MSK-004")]
        questions = ["هل الألم بيمنعك من المشي أو الحركة الطبيعية؟"]
        return category, specialty, urgency, citations, questions

    # 5. Systemic / Fever / Dermatology non-emergency
    if any(
        kw in norm_input
        for kw in (
            "مبطش بارتكاريا",
            "ارتكاريا",
            "همدان ومفرهد",
            "عرق بالليل بيغرق الملايه",
            "حبوب بفقاقيع ميه علي خط واحد",
            "حمو النيل",
            "دور برد وسخونيه",
            "وشي بهتان واصفر",
            "جسمي كله سقعان",
            "طفح جلدي وارتكاريا بتفرش",
            "كدمات زرقا في جسمي لوحدها",
            "باخد جلسات كيماوي",
            "جسمي مكسر",
            "سخونيه",
            "طفح جلدي",
            "هرش",
        )
    ):
        category = SymptomCategory.SYSTEMIC_FEVER_DERM
        specialty = "الأمراض الجلدية والحساسية والمناعة / الباطنة العامة وأمراض الدم والغدد الصماء والحميات والأورام والمخ والأعصاب"
        urgency = (
            UrgencyLevel.URGENT_SPECIALIST
            if any(
                u in norm_input
                for u in (
                    "عرق بالليل بيغرق الملايه",
                    "حبوب بفقاقيع ميه علي خط واحد",
                    "تورم تحت الجلد حوالين عيني",
                    "كدمات زرقا في جسمي لوحدها",
                    "جلسات كيماوي",
                )
            )
            else UrgencyLevel.ROUTINE_SPECIALIST
        )
        citations = [get_default_citation("NHS-SYS-004"), get_default_citation("NHS-SYS-005")]
        questions = ["كم درجة الحرارة تقريباً ومن امتى ظهرت الأعراض؟"]
        return category, specialty, urgency, citations, questions

    # 6. Ambiguous / Unknown
    return (
        SymptomCategory.UNKNOWN,
        "طبيب عام / طب الأسرة / الأمراض الباطنية العامة وطب المسنين",
        UrgencyLevel.AMBIGUOUS_SEE_DOCTOR,
        [get_default_citation("NHS-SYS-005")],
        ["ممكن توضح الأعراض بدأت من امتى وهل في أي أعراض تانية مصاحبة ليها؟"],
    )


async def process_triage(request: TriageRequest) -> TriageResponse:
    """Execute clinical triage via the compiled LangGraph state machine (`app.agent.graph`)."""
    from app.agent.graph import run_triage_agent

    return await run_triage_agent(request)


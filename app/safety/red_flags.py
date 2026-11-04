"""Deterministic, zero-LLM red-flag rule engine for Egyptian Arabic and MSA acute symptoms."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.triage import SymptomCategory, UrgencyLevel

# Arabic normalization table for resilient matching across hamzas, alef variants, and teh marbuta
_ALEF_VARIANTS = re.compile(r"[إأآٱ]")
_TATWEEL = re.compile(r"\u0640")
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")

_SLANG_PATH: Path = Path(__file__).resolve().parent.parent.parent / "data" / "egyptian_medical_slang.json"


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for deterministic rule matching."""
    cleaned = _DIACRITICS.sub("", text)
    cleaned = _TATWEEL.sub("", cleaned)
    cleaned = _ALEF_VARIANTS.sub("ا", cleaned)
    cleaned = cleaned.replace("ى", "ي").replace("ة", "ه")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@dataclass(frozen=True)
class RedFlagRule:
    """A single deterministic red-flag rule definition."""

    rule_id: str
    category: SymptomCategory
    canonical_name_ar: str
    pattern: re.Pattern[str]
    recommended_specialty_ar: str = "قسم الطوارئ والحالات الحرجة"
    linked_doc_ids: tuple[str, ...] = ()


def _compile_norm(raw_pattern: str) -> re.Pattern[str]:
    """Compile a regex pattern with normalized Arabic characters."""
    return re.compile(normalize_arabic(raw_pattern), re.IGNORECASE)


def _phrase_to_regex(phrase: str) -> str:
    """Convert a normalized Arabic phrase into a whitespace-resilient regex fragment."""
    norm = normalize_arabic(phrase)
    tokens = [re.escape(tok) for tok in norm.split() if tok]
    return r"\s+".join(tokens)


def _load_slang_red_flag_rules() -> tuple[RedFlagRule, ...]:
    """Load `is_red_flag: true` entries from `data/egyptian_medical_slang.json`."""
    if not _SLANG_PATH.exists():
        return ()
    raw_data: Any = json.loads(_SLANG_PATH.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = (
        raw_data if isinstance(raw_data, list) else raw_data.get("entries", [])
    )
    rules: list[RedFlagRule] = []
    for entry in entries:
        if not entry.get("is_red_flag"):
            continue
        phrases = entry.get("egyptian_phrases", [])
        if not phrases:
            continue
        joined = "|".join(_phrase_to_regex(p) for p in phrases if p.strip())
        if not joined:
            continue
        rules.append(
            RedFlagRule(
                rule_id=str(entry["slang_id"]),
                category=SymptomCategory(entry["category"]),
                canonical_name_ar=str(entry["clinical_term_ar"]),
                pattern=re.compile(f"(?:{joined})", re.IGNORECASE),
                recommended_specialty_ar=str(
                    entry.get("recommended_specialty", "قسم الطوارئ والحالات الحرجة")
                ),
                linked_doc_ids=tuple(entry.get("linked_doc_ids", [])),
            )
        )
    return tuple(rules)


CORE_RED_FLAG_RULES: tuple[RedFlagRule, ...] = (
    # Cardiopulmonary red flags
    RedFlagRule(
        rule_id="RF-CARDIO-01",
        category=SymptomCategory.CARDIOPULMONARY,
        canonical_name_ar="ضغط شديد على الصدر (طابوقة على الصدر)",
        pattern=_compile_norm(
            r"(طابوقه\s+(?:كابسه\s+)?علي\s+(?:نص\s+)?(?:صدري|صدره|صدرها)|بلاطه\s+(?:كاتمه\s+)?علي\s+صدري|حجر\s+(?:كابس\s+)?علي\s+(?:صدري|نفسي)|ضغط\s+شديد\s+في\s+الصدر)"
        ),
        recommended_specialty_ar="طوارئ المستشفى فوراً (قسم القلب والعناية المركزة)",
        linked_doc_ids=("NHS-CARDIO-001", "WHO-CARDIO-005"),
    ),
    RedFlagRule(
        rule_id="RF-CARDIO-02",
        category=SymptomCategory.CARDIOPULMONARY,
        canonical_name_ar="ضيق تنفس حاد (كرشة نفس شديدة / اختناق)",
        pattern=_compile_norm(
            r"(كرشه\s+نفس\s+شديده|ضيق\s+تنفس\s+شديد|مش\s+قادر\s+(?:اخد|ياخد|يلقط|القط)\s+(?:نفسي|نفسه|النفس)|(?:نفسي|نفسه|نفسها)\s+مقطوع(?:\s+فجاه)?\s+و(?:بيفرفر|بفرفر|مش\s+قادر)|(?:بفرفر|بيفرفر|بتفرفر)\s+(?:من\s+النفس|ومش\s+(?:قادر|عارف))|مش\s+قادر\s+(?:انطق|ينطق|اكمل|يكمل)\s+جمله\s+علي\s+بعضها|اختناق\s+حاد|شفايفي\s+مزرقه|شفايفه\s+وصوابعه\s+ازرقوا)"
        ),
        recommended_specialty_ar="طوارئ المستشفى فوراً (قسم الطوارئ والرعاية المركزة والصدر)",
        linked_doc_ids=("NHS-CARDIO-002",),
    ),
    RedFlagRule(
        rule_id="RF-CARDIO-03",
        category=SymptomCategory.CARDIOPULMONARY,
        canonical_name_ar="ألم بالصدر يمتد للذراع الأيسر أو الفك",
        pattern=_compile_norm(
            r"(الم\s+في\s+الصدر\s+مسمع\s+في\s+(?:دراعي|دراعه)\s+الشمال|(?:وجع\s+في\s+صدري|الوجع)\s+مسمع\s+في\s+(?:دراعي|دراعه)(?:\s+الشمال)?|الم\s+بالصدر\s+يمتد\s+للذراع\s+الايسر|صدري\s+بيوجعني\s+ومسمع\s+في\s+كتفي\s+الشمال)"
        ),
        recommended_specialty_ar="طوارئ المستشفى فوراً (قسم القلب والأوعية الدموية)",
        linked_doc_ids=("NHS-CARDIO-001", "WHO-CARDIO-005"),
    ),
    RedFlagRule(
        rule_id="RF-CARDIO-04",
        category=SymptomCategory.CARDIOPULMONARY,
        canonical_name_ar="سعال مصحوب بدم أو بلغم مدمم",
        pattern=_compile_norm(
            r"((?:بكح|بيكح|بتكح|كحيت)\s+دم(?:\s+احمر)?|البلغم\s+نازل\s+فيه\s+دم\s+احمر|(?:جبت|جاب)\s+دم\s+مع\s+الكحه)"
        ),
        recommended_specialty_ar="طوارئ الصدر والجهاز التنفسي فوراً",
        linked_doc_ids=("NHS-CARDIO-004", "NHS-CARDIO-002"),
    ),
    RedFlagRule(
        rule_id="RF-CARDIO-05",
        category=SymptomCategory.CARDIOPULMONARY,
        canonical_name_ar="خفقان القلب المصحوب بدوار شديد أو إغماء",
        pattern=_compile_norm(
            r"((?:قلبي|قلبه)\s+بيدق\s+(?:جامد|بسرعه\s+رهيبه).*?(?:هيغمي\s+عليا|واغمي\s+عليه|وقعت\s+من\s+طولي)|رفرفه\s+في\s+صدري\s+ووقعت\s+من\s+طولي)"
        ),
        recommended_specialty_ar="طوارئ القلب وكهرباء القلب فوراً",
        linked_doc_ids=("NHS-CARDIO-003",),
    ),
    # Neurological / Stroke / Syncope / Ophthalmic red flags
    RedFlagRule(
        rule_id="RF-NEURO-01",
        category=SymptomCategory.NEUROLOGICAL_ENT_OPHTH,
        canonical_name_ar="تنميل أو ضعف نصفي مفاجئ أو اعوجاج الفم وثقل اللسان",
        pattern=_compile_norm(
            r"(تنميل\s+في\s+نص\s+(?:جسمي|جسمه)|تنميل\s+في\s+نصف\s+الجسم|نص\s+(?:جسمي|جسمه)(?:\s+الشمال|\s+اليمين)?\s+(?:وقف|ساب)|(?:بقي|بقه|بقها|وشي|وشه)\s+(?:بقي\s+)?(?:معوج|اتعوج)|(?:لساني|لسانه)\s+تقل(?:\s+في\s+الكلام)?|ثقل\s+في\s+اللسان\s+فجاه|مش\s+قادر\s+(?:انطق|ينطق|يرفع\s+دراعه\s+ورجله)|شلل\s+نصفي)"
        ),
        recommended_specialty_ar="طوارئ المستشفى فوراً (وحدة السكتة الدماغية والمخ والأعصاب)",
        linked_doc_ids=("NHS-NEURO-001", "MAYO-NEURO-002"),
    ),
    RedFlagRule(
        rule_id="RF-NEURO-02",
        category=SymptomCategory.NEUROLOGICAL_ENT_OPHTH,
        canonical_name_ar="فقدان الوعي أو التشنجات الحادة",
        pattern=_compile_norm(
            r"(بلع\s+لسانه|فقد\s+الوعي|مغمي\s+عليه\s+ومش\s+بيفوق|تشنجات\s+مستمره|صرع\s+شغال)"
        ),
        recommended_specialty_ar="طوارئ المخ والأعصاب والإنعاش",
        linked_doc_ids=("NHS-NEURO-001",),
    ),
    RedFlagRule(
        rule_id="RF-NEURO-03",
        category=SymptomCategory.NEUROLOGICAL_ENT_OPHTH,
        canonical_name_ar="صداع رعدي مفاجئ وشديد للغاية",
        pattern=_compile_norm(
            r"(صداع\s+فجاه(?:\s+في\s+ثانيه)?\s+زي\s+ما\s+يكون\s+حد\s+ضربني\s+بشاكوش|(?:راسي|راسه)\s+هتنفجر\s+من\s+صداع\s+طلع\s+في\s+ثانيه|ابشع\s+(?:صداع|وجع)\s+(?:جالي|شوفته)\s+في\s+حياتي)"
        ),
        recommended_specialty_ar="طوارئ المستشفى فوراً (قسم المخ والأعصاب وجراحة المخ والأعصاب)",
        linked_doc_ids=("NHS-NEURO-001",),
    ),
    RedFlagRule(
        rule_id="RF-NEURO-04",
        category=SymptomCategory.NEUROLOGICAL_ENT_OPHTH,
        canonical_name_ar="فقدان مفاجئ للبصر أو ظهور ستارة مظلمة بالعين",
        pattern=_compile_norm(
            r"(النور\s+قطع\s+في\s+(?:عيني|عينه)(?:\s+اليمين|\s+الشمال)?\s+فجاه|(?:عيني|عينه)\s+ضلمت\s+فجاه|ستاره\s+سوده\s+نازله\s+(?:علي\s+عيني|مغطيه\s+النظر))"
        ),
        recommended_specialty_ar="طوارئ طب وجراحة العيون فوراً",
        linked_doc_ids=("NHS-NEURO-003",),
    ),
    RedFlagRule(
        rule_id="RF-NEURO-05",
        category=SymptomCategory.NEUROLOGICAL_ENT_OPHTH,
        canonical_name_ar="ألم حاد وشديد بالعين مع احمرار وزغللة وهالات ضوئية وقيء",
        pattern=_compile_norm(
            r"((?:عيني|عينه)(?:\s+اليمين|\s+الشمال)?\s+حمرا\s+دم\s+وبتنقح.*?(?:ترجيع|بستفرغ|هالات\s+نور)|وجع\s+رهيب\s+جوه\s+عيني\s+مع\s+زغلله\s+وهالات\s+نور)"
        ),
        recommended_specialty_ar="طوارئ العيون والرمد فوراً",
        linked_doc_ids=("NHS-NEURO-003",),
    ),
    # Gastrointestinal / Hemorrhagic / Acute Abdomen red flags
    RedFlagRule(
        rule_id="RF-GI-01",
        category=SymptomCategory.GASTROINTESTINAL,
        canonical_name_ar="قيء دموي أو براز أسود قاتم أو نزيف جهاز هضمي حاد",
        pattern=_compile_norm(
            r"(ترجيع\s+دم|(?:برجع|بيرجع|بستفرغ|استفرغت|استفرغ)\s+دم(?:\s+احمر)?|شبه\s+تفل\s+القهوه|قيء\s+(?:دموي|مدمم)|استفراغ\s+دم|براز(?:\s+لونه)?\s+اسود\s+زي\s+الزفت|نزيف\s+شرجي\s+غزير)"
        ),
        recommended_specialty_ar="طوارئ المستشفى فوراً (مناظير الجهاز الهضمي والكبد والعناية المركزة)",
        linked_doc_ids=("NHS-GI-003", "NHS-GI-002"),
    ),
    RedFlagRule(
        rule_id="RF-GI-02",
        category=SymptomCategory.GASTROINTESTINAL,
        canonical_name_ar="ألم حاد وشديد بالبطن مع تحجر جدار البطن",
        pattern=_compile_norm(
            r"((?:بطني|بطنه)\s+محجره\s+زي\s+الخشبه|وجع\s+رهيب\s+زي\s+السكاكين\s+طلع\s+فجاه|مغص\s+وسكاكين\s+بتقطع\s+في\s+بطني\s+فجاه)"
        ),
        recommended_specialty_ar="طوارئ الجراحة العامة والجهاز الهضمي فوراً",
        linked_doc_ids=("NHS-GI-002",),
    ),
    RedFlagRule(
        rule_id="RF-GI-03",
        category=SymptomCategory.GASTROINTESTINAL,
        canonical_name_ar="انقطاع تام للبراز والغازات مع انتفاخ شديد بالبطن وقيء مراري أخضر",
        pattern=_compile_norm(
            r"((?:بطني|بطنه)\s+منفوخه\s+ومقفوله\s+خالص.*?(?:لا\s+(?:حمام|بعمل\s+حمام)\s+ولا\s+(?:حتي\s+)?ريح|(?:بستفرغ|ترجيع)\s+(?:ميه\s+خضرا|اخضر))|امساك\s+تام\s+ومفيش\s+حتي\s+غازات\s+بتعدي\s+وبستفرغ\s+ميه\s+خضرا)"
        ),
        recommended_specialty_ar="طوارئ الجراحة العامة والمستشفى فوراً",
        linked_doc_ids=("NHS-GI-002", "NHS-GI-004", "NHS-GI-005"),
    ),
    RedFlagRule(
        rule_id="RF-GI-04",
        category=SymptomCategory.GASTROINTESTINAL,
        canonical_name_ar="قيء وإسهال مستمر مع انقطاع البول وعلامات جفاف شديد",
        pattern=_compile_norm(
            r"(ترجيع\s+واسهال\s+مش\s+مبطل.*?(?:قاطع\s+بول|مفيش\s+بول|معدتي\s+مش\s+قابله\s+نقطه\s+ميه)|بستفرغ\s+اي\s+حاجه\s+بشربها\s+ومفيش\s+بول\s+من\s+امبارح)"
        ),
        recommended_specialty_ar="طوارئ الباطنة والجهاز الهضمي",
        linked_doc_ids=("NHS-GI-004",),
    ),
    # Musculoskeletal / Spine / Orthopedic red flags
    RedFlagRule(
        rule_id="RF-MSK-01",
        category=SymptomCategory.MUSCULOSKELETAL,
        canonical_name_ar="ألم أسفل الظهر مع تنميل الساقين ومنطقة المقعدة وفقدان التحكم بالبول",
        pattern=_compile_norm(
            r"(تنميل\s+في\s+الرجلين\s+الاتنين.*?(?:البول\s+(?:بيفلت|فلت)|مش\s+حاسس\s+بمنطقه\s+المقعده)|مش\s+حاسس\s+بمنطقه\s+المقعده\s+خالص|تنميل\s+بين\s+الفخدين\s+مع\s+وجع\s+الضهر\s+والبنطلون\s+بيتبل)"
        ),
        recommended_specialty_ar="طوارئ جراحة المخ والأعصاب والعمود الفقري فوراً",
        linked_doc_ids=("NHS-MSK-001", "NHS-MSK-002"),
    ),
    RedFlagRule(
        rule_id="RF-MSK-02",
        category=SymptomCategory.MUSCULOSKELETAL,
        canonical_name_ar="سقوط القدم الحاد أو ضعف حركي متفاقم بالساقين",
        pattern=_compile_norm(
            r"(مشط\s+(?:رجلي|رجله)\s+سقط(?:\s+فجاه)?|كهربا\s+نازله\s+في\s+الرجلين\s+الاتنين\s+ومش\s+قادر\s+اقف)"
        ),
        recommended_specialty_ar="طوارئ جراحة المخ والأعصاب والعظام فوراً",
        linked_doc_ids=("NHS-MSK-002", "NHS-MSK-001"),
    ),
    RedFlagRule(
        rule_id="RF-MSK-03",
        category=SymptomCategory.MUSCULOSKELETAL,
        canonical_name_ar="اعوجاج وتشوه بالطرف بعد إصابة مع برودة أو ازرقاق وتنميل الأصابع",
        pattern=_compile_norm(
            r"(سمعت\s+طرقعه\s+في\s+(?:رجلي|رجله)\s+.*?(?:العضمه\s+معووجه|مش\s+قادر\s+ادوس)|(?:دراعي|رجلي)\s+اتلوي\s+وشكله\s+متغير\s+وصوابعي\s+منمله)"
        ),
        recommended_specialty_ar="طوارئ جراحة العظام والكسور فوراً",
        linked_doc_ids=("NHS-MSK-005", "MAYO-MSK-004"),
    ),
    RedFlagRule(
        rule_id="RF-MSK-04",
        category=SymptomCategory.MUSCULOSKELETAL,
        canonical_name_ar="تورم واحمرار وسخونة شديدة بالمفصل مع حمى وعدم القدرة على تحريكه",
        pattern=_compile_norm(
            r"((?:مفصل\s+)?(?:ركبتي|ركبته|المفصل)\s+(?:ورم\s+فجاه\s+زي\s+البالونه|وارمه\s+زي\s+البالونه|وارم\s+ومحمر\s+ومش\s+قادر\s+احركه\s+ملي\s+واحد))"
        ),
        recommended_specialty_ar="طوارئ جراحة العظام والروماتيزم فوراً",
        linked_doc_ids=("MAYO-MSK-004",),
    ),
    # Systemic / Anaphylaxis / Sepsis / Meningitis / SJS red flags
    RedFlagRule(
        rule_id="RF-SYS-01",
        category=SymptomCategory.SYSTEMIC_FEVER_DERM,
        canonical_name_ar="تورم مفاجئ بالشفاه واللسان والحلق مع ضيق تنفس حاد",
        pattern=_compile_norm(
            r"((?:شفايفي\s+ولساني|لساني)\s+(?:ورموا|ورم)(?:\s+فجاه)?\s+و(?:زوري\s+قفل|مش\s+قادر\s+ابلع)|زوري\s+قفل\s+فجاه|وشي\s+وزوري\s+اتنفخوا\s+ومش\s+عارف\s+ابلع|حساسيه\s+شديده\s+مع\s+ضيق\s+نفس)"
        ),
        recommended_specialty_ar="طوارئ المستشفى والحساسية والعناية المركزة فوراً",
        linked_doc_ids=("NHS-SYS-002", "NHS-SYS-004"),
    ),
    RedFlagRule(
        rule_id="RF-SYS-02",
        category=SymptomCategory.SYSTEMIC_FEVER_DERM,
        canonical_name_ar="حمى شديدة مع تشوش بالوعي ونهجان وتبقع الجلد وانقطاع البول",
        pattern=_compile_norm(
            r"((?:سخونيه\s+عاليه\s+جدا|سخونيه\s+مولعه|حراره\s+عاليه\s+جدا).*?(?:يخرف|بخرف|جلده\s+مبقع\s+ازرق|مفيش\s+بول\s+خالص)|جسمه\s+متلج\s+ومبقع\s+ازرق\s+ودايخ)"
        ),
        recommended_specialty_ar="طوارئ المستشفى والعناية المركزة والحميات فوراً",
        linked_doc_ids=("NHS-SYS-001",),
    ),
    RedFlagRule(
        rule_id="RF-SYS-03",
        category=SymptomCategory.SYSTEMIC_FEVER_DERM,
        canonical_name_ar="حمى شديدة مع تيبس الرقبة وحساسية للضوء وطفح جلدي لا يختفي بالضغط",
        pattern=_compile_norm(
            r"((?:رقبتي|رقبته)\s+مخشبه\s+مش\s+قادر\s+(?:احنيها|يحنيها)|(?:نقط|بقع)\s+حمرا\s+وبنفسجي\s+تحت\s+الجلد\s+مش\s+بتروح\s+لما\s+ادوس\s+عليها\s+بكوبايه)"
        ),
        recommended_specialty_ar="طوارئ المستشفى والحميات والمخ والأعصاب فوراً",
        linked_doc_ids=("WHO-SYS-003", "NHS-SYS-001"),
    ),
    RedFlagRule(
        rule_id="RF-SYS-04",
        category=SymptomCategory.SYSTEMIC_FEVER_DERM,
        canonical_name_ar="طفح جلدي متقشر مع فقاعات بالجلد وتقرحات بالفم والعينين وحمى",
        pattern=_compile_norm(
            r"(طفح\s+جلدي\s+و?ب?فقاقيع\s+بتقشر\s+(?:وتسلخ\s+)?الجلد|جلدي\s+بيتسلخ\s+كانه\s+محروق\s+مع\s+سخونيه)"
        ),
        recommended_specialty_ar="طوارئ المستشفى والجلدية والعناية المركزة فوراً",
        linked_doc_ids=("NHS-SYS-004",),
    ),
)

RED_FLAG_RULES: tuple[RedFlagRule, ...] = CORE_RED_FLAG_RULES + _load_slang_red_flag_rules()

# Negation markers that immediately precede a red flag phrase (e.g., "مفيش ترجيع دم", "لا يوجد ألم في الصدر")
_NEGATION_PREFIX = _compile_norm(
    r"(?:مفيش|مافيش|معنديش|ماعنديش|لا\s+يوجد|لا\s+اشعر\s+بـ?|لا\s+اعاني\s+من|بدون|من\s+غير)(?:\s+لا\s+\S+\s+ولا)?\s+$"
)


@dataclass(frozen=True)
class RedFlagEvaluation:
    """Detailed outcome from the deterministic red-flag rule engine."""

    urgency_level: UrgencyLevel | None
    escalation_triggered: bool
    matched_rules: list[str]
    matched_phrases_ar: list[str]
    negated_red_flags: list[str]
    primary_category: SymptomCategory
    recommended_specialty_ar: str = "قسم الطوارئ والحالات الحرجة"
    linked_doc_ids: list[str] | None = None


def evaluate_red_flags(text: str) -> RedFlagEvaluation:
    """Evaluate input text for acute red flags, distinguishing positive matches from negated mentions."""
    if not text or not text.strip():
        return RedFlagEvaluation(
            urgency_level=None,
            escalation_triggered=False,
            matched_rules=[],
            matched_phrases_ar=[],
            negated_red_flags=[],
            primary_category=SymptomCategory.UNKNOWN,
            recommended_specialty_ar="قسم الطوارئ والحالات الحرجة",
            linked_doc_ids=[],
        )

    norm_text = normalize_arabic(text)
    matched_rules: list[str] = []
    matched_phrases_ar: list[str] = []
    negated_flags: list[str] = []
    negated_spans: list[tuple[int, int]] = []
    primary_category = SymptomCategory.UNKNOWN
    recommended_specialty_ar = "قسم الطوارئ والحالات الحرجة"
    linked_doc_ids: list[str] = []

    for rule in RED_FLAG_RULES:
        for match in rule.pattern.finditer(norm_text):
            start_idx, end_idx = match.start(), match.end()
            preceding_window = norm_text[max(0, start_idx - 40) : start_idx]
            if _NEGATION_PREFIX.search(preceding_window):
                overlaps_existing = any(
                    not (end_idx <= s or start_idx >= e) for s, e in negated_spans
                )
                if not overlaps_existing and rule.canonical_name_ar not in negated_flags:
                    negated_flags.append(rule.canonical_name_ar)
                    negated_spans.append((start_idx, end_idx))
            else:
                if rule.rule_id not in matched_rules:
                    matched_rules.append(rule.rule_id)
                if rule.canonical_name_ar not in matched_phrases_ar:
                    matched_phrases_ar.append(rule.canonical_name_ar)
                if primary_category == SymptomCategory.UNKNOWN:
                    primary_category = rule.category
                    recommended_specialty_ar = rule.recommended_specialty_ar
                for doc_id in rule.linked_doc_ids:
                    if doc_id not in linked_doc_ids:
                        linked_doc_ids.append(doc_id)

    if matched_rules:
        return RedFlagEvaluation(
            urgency_level=UrgencyLevel.EMERGENCY_ESCALATION,
            escalation_triggered=True,
            matched_rules=matched_rules,
            matched_phrases_ar=matched_phrases_ar,
            negated_red_flags=negated_flags,
            primary_category=primary_category,
            recommended_specialty_ar=recommended_specialty_ar,
            linked_doc_ids=linked_doc_ids,
        )

    return RedFlagEvaluation(
        urgency_level=None,
        escalation_triggered=False,
        matched_rules=[],
        matched_phrases_ar=[],
        negated_red_flags=negated_flags,
        primary_category=SymptomCategory.UNKNOWN,
        recommended_specialty_ar="قسم الطوارئ والحالات الحرجة",
        linked_doc_ids=[],
    )


def check_red_flags(text: str) -> UrgencyLevel | None:
    """Deterministic zero-LLM rule check returning `UrgencyLevel.EMERGENCY_ESCALATION` if any red flag matches."""
    result = evaluate_red_flags(text)
    return result.urgency_level


def apply_supremacy_rule(
    rule_urgency: UrgencyLevel | None,
    llm_urgency: UrgencyLevel,
) -> UrgencyLevel:
    """Enforce the Supremacy Rule: `max(rule, llm)` so deterministic safety rules can never be downgraded."""
    if rule_urgency is None:
        return llm_urgency
    return UrgencyLevel(max(int(rule_urgency), int(llm_urgency)))

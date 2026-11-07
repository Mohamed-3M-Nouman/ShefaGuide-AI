"""Acceptance tests for the Egyptian medical-slang normalizer (`app/rag/dialect_normalizer.py`).

Acceptance criteria:
  * 20 colloquial complaints are normalized to the right lexicon entry (100% pass).
  * Each call completes in under 50 ms.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.rag.dialect_normalizer import (
    DialectNormalizer,
    MatchType,
    get_dialect_normalizer,
    normalize_dialect,
)
from app.safety.pii_scrubber import REDACTED_TOKEN, scrub_pii
from app.schemas.triage import SymptomCategory

ROOT = Path(__file__).resolve().parent.parent
LEXICON = {
    entry["slang_id"]: entry
    for entry in json.loads((ROOT / "data" / "egyptian_medical_slang.json").read_text("utf-8"))
}
LATENCY_BUDGET_MS = 50.0

# (patient complaint, expected slang_id, expected is_red_flag)
TWENTY_SENTENCES: list[tuple[str, str, bool]] = [
    ("عندي كرشة نفس شديدة ومش قادر أتكلم", "EG-CARDIO-003", True),
    ("فم المعدة قافش عليا من امبارح", "EG-GI-007", False),
    ("أنا اسمي أحمد محمد ورقمي 01012345678، حاسس بطابوقة على صدري من ساعة", "EG-CARDIO-001", True),
    ("أبويا حاسس بطابوقة كابسة على نص صدره", "EG-CARDIO-001", True),
    ("بقالي أسبوعين عندي كرشة نفس لما بطلع السلم للدور التاني", "EG-CARDIO-008", False),
    ("صدري بيزيق وبيصفر زي القطة بالليل لما الجو يبرد", "EG-CARDIO-010", False),
    ("كل ما أشرب قهوة قلبي بيفوت دقة ويسحب سحبة", "EG-CARDIO-007", False),
    ("جالي صداع فجأة زي ما يكون حد ضربني بشاكوش على نفوخي", "EG-NEURO-001", True),
    ("نص دماغي بينقح عليا ومش طايق النور ولا الصوت", "EG-NEURO-008", False),
    ("الدنيا بتلف بيا والأوضة بتدور لما بتقلب في السرير الصبح", "EG-NEURO-006", False),
    ("ودني مكتومة وبتصفر من ساعة ما نزلت البحر", "EG-NEURO-010", False),
    ("بستفرغ دم أحمر من الصبح وحاسس بدوخة", "EG-GI-001", True),
    ("قولوني قايم عليا ومليان غازات بعد كل أكلة", "EG-GI-008", False),
    ("حُرقان ونار قايدة فى فم المعدة بالليل", "EG-GI-007", False),
    ("عرق النسا شابك من القطنية ونازل بكهربا لحد كعب رجلي", "EG-MSK-006", False),
    ("ضهري قافش عليا من تحت ومش عارف أوطي أجيب حاجة", "EG-MSK-007", False),
    ("مشط رجلي سقط ومش قادر أرفعه وأنا بمشي مع عرق النسا", "EG-MSK-002", True),
    ("عندي خشونة في ركبي وبتطقطق لما بطلع السلم", "EG-MSK-009", False),
    ("حمو النيل مالي ضهري ورقبتي من الحر والعرق", "EG-SYS-011", False),
    ("جِسْمِي كُلُّه مبطّش بأرتكاريا وهرش هيجننى", "EG-SYS-006", False),
]


def test_twenty_sentence_set_has_exactly_twenty_cases() -> None:
    assert len(TWENTY_SENTENCES) == 20


@pytest.mark.parametrize(("complaint", "slang_id", "is_red_flag"), TWENTY_SENTENCES)
def test_twenty_colloquial_complaints_are_normalized(
    complaint: str, slang_id: str, is_red_flag: bool
) -> None:
    scrubbed = scrub_pii(complaint)  # the normalizer always runs after PII scrubbing
    result = normalize_dialect(scrubbed)

    matched = {match.slang_id: match for match in result.active_matches}
    assert slang_id in matched, f"{slang_id} not found; got {list(matched)}"

    match = matched[slang_id]
    entry = LEXICON[slang_id]
    assert match.clinical_term_en == entry["clinical_term_en"]
    assert match.clinical_term_ar == entry["clinical_term_ar"]
    assert match.category == SymptomCategory(entry["category"])
    assert match.is_red_flag is is_red_flag
    assert list(match.linked_doc_ids) == entry["linked_doc_ids"]
    assert match.recommended_specialty == entry["recommended_specialty"]
    assert result.has_red_flag is is_red_flag
    assert result.primary_category == SymptomCategory(entry["category"])
    assert result.elapsed_ms < LATENCY_BUDGET_MS


def test_each_call_is_under_50ms() -> None:
    normalizer = get_dialect_normalizer()  # lexicon is loaded once, outside the timed loop
    long_complaint = " ".join(text for text, _, _ in TWENTY_SENTENCES)
    samples = [text for text, _, _ in TWENTY_SENTENCES] + [long_complaint]

    worst_ms = 0.0
    for _ in range(25):
        for text in samples:
            started = time.perf_counter()
            normalizer.normalize(text)
            worst_ms = max(worst_ms, (time.perf_counter() - started) * 1000.0)
    assert worst_ms < LATENCY_BUDGET_MS, f"worst call took {worst_ms:.2f} ms"


def test_lexicon_is_loaded_once_and_shared() -> None:
    assert get_dialect_normalizer() is get_dialect_normalizer()
    assert get_dialect_normalizer().entry_count == len(LEXICON)


def test_every_lexicon_phrase_matches_its_own_entry_exactly() -> None:
    normalizer = get_dialect_normalizer()
    failures = []
    for slang_id, entry in LEXICON.items():
        for phrase in entry["egyptian_phrases"]:
            exact_ids = {
                match.slang_id
                for match in normalizer.normalize(phrase).matches
                if match.match_type is MatchType.EXACT
            }
            if slang_id not in exact_ids:
                failures.append((slang_id, phrase))
    assert failures == []


def test_negated_symptoms_are_reported_but_not_active() -> None:
    result = normalize_dialect(
        "مفيش كرشة نفس شديدة ولا طابوقة على صدري، بس عندي كحة ناشفة مسكتني مش راضية تفك بقالها شهر"
    )
    negated = {match.slang_id for match in result.negated_matches}
    active = {match.slang_id for match in result.active_matches}

    assert {"EG-CARDIO-003", "EG-CARDIO-001"} <= negated
    assert "EG-CARDIO-011" in active
    assert result.has_red_flag is False


def test_negation_does_not_leak_to_a_later_affirmed_symptom() -> None:
    result = normalize_dialect("مفيش سخونية بس عندي كحة ناشفة مسكتني مش راضية تفك بقالها شهر")
    assert [m.slang_id for m in result.active_matches] == ["EG-CARDIO-011"]


def test_weak_red_flag_evidence_is_surfaced_without_escalating() -> None:
    result = normalize_dialect("عندي كرشة نفس")
    assert result.primary_category == SymptomCategory.CARDIOPULMONARY
    assert result.has_red_flag is False
    assert "EG-CARDIO-003" in {match.slang_id for match in result.possible_red_flags}


@pytest.mark.parametrize("text", ["", "   ", "أحسن مستشفى خاص في المنصورة إيه؟"])
def test_inputs_without_slang_return_no_matches(text: str) -> None:
    result = normalize_dialect(text)
    assert result.matches == ()
    assert result.primary_category == SymptomCategory.UNKNOWN
    assert result.has_red_flag is False
    assert result.linked_doc_ids == []


def test_redacted_placeholders_pass_through_untouched() -> None:
    scrubbed = scrub_pii("اسمي منى علي وتليفوني 01198765432 وعندي حمو النيل في ضهري")
    result = normalize_dialect(scrubbed)
    assert REDACTED_TOKEN in result.normalized_text
    assert "01198765432" not in result.normalized_text
    assert result.active_matches[0].slang_id == "EG-SYS-011"


def test_enriched_query_appends_standard_clinical_terms() -> None:
    result = normalize_dialect("فم المعدة قافش عليا")
    query = result.enriched_query()
    assert "فم المعدة قافش عليا" in query
    assert LEXICON["EG-GI-007"]["clinical_term_en"] in query


def test_missing_lexicon_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        DialectNormalizer(lexicon_path=tmp_path / "missing.json")

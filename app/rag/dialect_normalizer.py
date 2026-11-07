"""Egyptian colloquial medical-slang normalizer.

Maps Egyptian Arabic symptom expressions (e.g. "كرشة نفس", "فم المعدة قافش") found in a
PII-scrubbed patient complaint to standardized clinical terms using the curated lexicon in
`data/egyptian_medical_slang.json`.

The lexicon is loaded into memory once. Matching is deterministic and runs in two tiers:

1. **Exact** – a lexicon phrase appears verbatim in the complaint after Arabic normalization
   (hamza/alef variants, teh marbuta, diacritics, tatweel and whitespace are ignored).
2. **Partial** – the complaint paraphrases a lexicon phrase. Every phrase is reduced to
   light-stemmed content words and indexed by its adjacent-word bigrams; bigrams shared by
   many entries are discarded so only distinctive cues remain. An entry matches when the
   weighted cue score reaches `min_partial_score`.

Each match is checked for a negation prefix ("مفيش", "معنديش", "من غير", ...) so that negated
symptoms are reported with `negated=True` instead of as active complaints.

This module only normalizes. Escalation decisions belong to `app.safety.red_flags`.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.safety.red_flags import normalize_arabic
from app.schemas.triage import SymptomCategory

DEFAULT_LEXICON_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "data" / "egyptian_medical_slang.json"
)

# A bigram cue shared by more entries than this is too generic to identify a symptom.
_MAX_CUE_ENTRY_FREQUENCY: int = 2
# Cue weight by the number of lexicon entries that share the bigram.
_CUE_WEIGHTS: dict[int, float] = {1: 1.0, 2: 0.5}
# The first bigram of a lexicon phrase is usually the idiom itself ("كرشة نفس", "فم المعدة",
# "عرق النسا"), so it counts as a full cue even when two entries share it.
_LEADING_CUE_WEIGHT: float = 1.0
# Partial matches never reach the confidence of a verbatim lexicon phrase.
_MAX_PARTIAL_CONFIDENCE: float = 0.95
# A red-flag entry counts toward `has_red_flag` only at or above this confidence (an exact
# phrase, or at least two independent cues). Weaker red-flag hits are still reported
# through `possible_red_flags`.
RED_FLAG_MIN_CONFIDENCE: float = 0.6

_ARABIC_LETTERS: str = "ء-ي"
_TOKEN_PATTERN: re.Pattern[str] = re.compile(rf"[{_ARABIC_LETTERS}]+|\d+")


def _norm_set(words: str) -> frozenset[str]:
    return frozenset(normalize_arabic(word) for word in words.split())


# Function words and Egyptian fillers that carry no symptom meaning.
_STOPWORDS: frozenset[str] = _norm_set(
    """
    في فى على علي من مع عن لما ما مش زي اللي الي اللى او أو ولا لا بس خالص اوي أوي جدا جداً
    كتير شوية حاجة عليا ليا بيا فيا انا أنا هو هي ده دي دا كل لحد لغاية بعد قبل يا قوي لو
    اني إني ان إن عشان بقالي بقاله بقالها عندي عنده عندها حاسس حاسة بحس جالي ومش مفيش ومفيش
    معاه معاها وانا وأنا تاني لوحده لوحدها النهاردة امبارح إمبارح الصبح بالليل حتى غير ساعات
    اول أول كأني كأنه كأنها وكأن إنه انه إنها انها بتاعي بتاعتي لسه برضه يعني
    """
)

# Generic modifiers (sides, durations, intensity, positions) that would otherwise pair with
# any body part and create false cues such as "رجلي الشمال" or "أربع أيام".
_GENERIC_WORDS: frozenset[str] = _norm_set(
    """
    شمال الشمال يمين اليمين جنب الجنب اتنين الاتنين تلات تلاتة أربع اربع خمس يوم يومين ايام
    أيام اسبوع أسبوع اسبوعين أسبوعين شهر شهرين ساعة ساعتين فيه فيها تحت فوق جوه بره ورا قدام
    فجأة فجاه بسرعة كله كلها مرة بتروح وتيجي بيروح وبيجي بيجي بتيجي معا
    """
)
# Intensity words ("شديدة", "رهيب") are deliberately NOT generic: they separate red-flag entries
# such as "كرشة نفس شديدة" from their routine counterparts.

# A negator immediately before the symptom, optionally in the forms "مفيش X ولا <symptom>"
# or "لا X ولا <symptom>". Mirrors the anchored negation logic of `app.safety.red_flags`.
_NEGATION_PREFIX: re.Pattern[str] = re.compile(
    normalize_arabic(
        r"(?:مفيش|مافيش|معنديش|ماعنديش|لا\s+يوجد|لا\s+اشعر\s+بـ?|لا\s+اعاني\s+من|بدون|من\s+غير)"
        r"(?:\s+لا)?(?:(?:\s+\S+){1,3}\s+ولا)?\s+$"
    )
)
_NEGATION_WINDOW_CHARS: int = 40


class MatchType(str, Enum):
    """How a lexicon entry was recognized in the complaint."""

    EXACT = "exact"
    PARTIAL = "partial"


class SlangMatch(BaseModel):
    """One Egyptian slang expression mapped to its standardized clinical meaning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slang_id: str
    matched_text: str = Field(..., description="Matched span of the normalized complaint.")
    match_type: MatchType
    confidence: float = Field(..., gt=0.0, le=1.0)
    clinical_term_en: str
    clinical_term_ar: str
    category: SymptomCategory
    is_red_flag: bool
    recommended_specialty: str
    linked_doc_ids: tuple[str, ...]
    negated: bool = Field(
        default=False, description="True when the patient explicitly denied this symptom."
    )
    start: int = Field(..., ge=0, description="Start offset in `normalized_text`.")
    end: int = Field(..., ge=0, description="End offset in `normalized_text`.")


class NormalizationResult(BaseModel):
    """Outcome of normalizing one patient complaint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_text: str
    normalized_text: str
    matches: tuple[SlangMatch, ...] = ()
    elapsed_ms: float = Field(default=0.0, ge=0.0)

    @property
    def active_matches(self) -> tuple[SlangMatch, ...]:
        """Matches the patient affirmed, i.e. excluding negated symptoms."""
        return tuple(match for match in self.matches if not match.negated)

    @property
    def negated_matches(self) -> tuple[SlangMatch, ...]:
        """Symptoms the patient explicitly denied."""
        return tuple(match for match in self.matches if match.negated)

    @property
    def red_flag_matches(self) -> tuple[SlangMatch, ...]:
        """Affirmed red-flag expressions backed by strong evidence (exact or high-coverage partial)."""
        return tuple(
            match
            for match in self.active_matches
            if match.is_red_flag and match.confidence >= RED_FLAG_MIN_CONFIDENCE
        )

    @property
    def possible_red_flags(self) -> tuple[SlangMatch, ...]:
        """Affirmed red-flag entries matched only weakly; surfaced for the severity tool, not escalated."""
        return tuple(
            match
            for match in self.active_matches
            if match.is_red_flag and match.confidence < RED_FLAG_MIN_CONFIDENCE
        )

    @property
    def has_red_flag(self) -> bool:
        """True when the complaint affirms a red-flag expression with strong evidence."""
        return bool(self.red_flag_matches)

    @property
    def clinical_terms_en(self) -> list[str]:
        return _unique(match.clinical_term_en for match in self.active_matches)

    @property
    def clinical_terms_ar(self) -> list[str]:
        return _unique(match.clinical_term_ar for match in self.active_matches)

    @property
    def categories(self) -> list[SymptomCategory]:
        return _unique(match.category for match in self.active_matches)

    @property
    def primary_category(self) -> SymptomCategory:
        """Category of the strongest affirmed match, or UNKNOWN when nothing matched."""
        active = self.active_matches
        return active[0].category if active else SymptomCategory.UNKNOWN

    @property
    def linked_doc_ids(self) -> list[str]:
        return _unique(doc_id for match in self.active_matches for doc_id in match.linked_doc_ids)

    def enriched_query(self) -> str:
        """Complaint plus standardized clinical terms, for retrieval against English guidelines."""
        parts = [self.input_text.strip(), *self.clinical_terms_en, *self.clinical_terms_ar]
        return "\n".join(part for part in parts if part)


def _unique(items: Any) -> list[Any]:
    return list(dict.fromkeys(items))


def _stem(token: str) -> str:
    """Light, symmetric Egyptian Arabic stemmer: strips و/ال/بال/ب prefixes and ي/ه/ها suffixes.

    It is applied identically to the lexicon and to the complaint, so it only needs to be
    consistent, not linguistically complete.
    """
    if len(token) >= 4 and token.startswith("و"):
        token = token[1:]
    if len(token) >= 5 and token.startswith("بال"):
        token = token[3:]
    elif len(token) >= 4 and token.startswith("ال"):
        token = token[2:]
    elif len(token) >= 5 and token.startswith("ب"):
        token = token[1:]
    if len(token) >= 5 and token.endswith("ها"):
        token = token[:-2]
    elif len(token) >= 4 and token[-1] in "يه":
        token = token[:-1]
    return token


_STEMMED_NON_CUES: frozenset[str] = frozenset(
    _stem(word) for word in _STOPWORDS | _GENERIC_WORDS
)


@dataclass(frozen=True)
class _ContentToken:
    stem: str
    start: int
    end: int


def _content_tokens(normalized_text: str) -> list[_ContentToken]:
    """Tokenize normalized text into stemmed content words with their character spans."""
    tokens: list[_ContentToken] = []
    for match in _TOKEN_PATTERN.finditer(normalized_text):
        word = match.group()
        if word in _STOPWORDS or word in _GENERIC_WORDS:
            continue
        stem = _stem(word)
        if stem in _STEMMED_NON_CUES or len(stem) < 2:
            continue
        tokens.append(_ContentToken(stem=stem, start=match.start(), end=match.end()))
    return tokens


def _phrase_regex(phrase: str) -> str:
    tokens = [re.escape(token) for token in normalize_arabic(phrase).split() if token]
    return r"\s+".join(tokens)


@dataclass(frozen=True)
class _LexiconEntry:
    slang_id: str
    category: SymptomCategory
    clinical_term_en: str
    clinical_term_ar: str
    is_red_flag: bool
    recommended_specialty: str
    linked_doc_ids: tuple[str, ...]
    exact_pattern: re.Pattern[str]
    phrase_bigrams: tuple[frozenset[tuple[str, str]], ...]
    leading_bigrams: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _Cue:
    entry_idx: int
    match_weight: float  # decides acceptance and ranking (includes the leading-idiom boost)
    evidence_weight: float  # decides confidence (distinctiveness only)


@dataclass
class _PartialCandidate:
    score: float = 0.0
    evidence: float = 0.0
    start: int = -1
    end: int = -1
    matched_bigrams: set[tuple[str, str]] = field(default_factory=set)


class DialectNormalizer:
    """In-memory Egyptian medical-slang normalizer. Build once, call `normalize()` per request."""

    def __init__(
        self,
        lexicon_path: Path | str = DEFAULT_LEXICON_PATH,
        min_partial_score: float = 1.0,
    ) -> None:
        self.lexicon_path = Path(lexicon_path)
        self.min_partial_score = min_partial_score
        self._entries: tuple[_LexiconEntry, ...] = self._load_entries(self.lexicon_path)
        self._cue_index: dict[tuple[str, str], tuple[_Cue, ...]] = self._build_cue_index(
            self._entries
        )

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @staticmethod
    def _load_entries(path: Path) -> tuple[_LexiconEntry, ...]:
        if not path.exists():
            raise FileNotFoundError(f"Slang lexicon not found: {path}")
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        records: list[dict[str, Any]] = raw if isinstance(raw, list) else raw.get("entries", [])

        entries: list[_LexiconEntry] = []
        for record in records:
            phrases = [p for p in record.get("egyptian_phrases", []) if p and p.strip()]
            if not phrases:
                continue
            # Longest phrases first so the regex reports the most specific span.
            ordered = sorted(phrases, key=lambda p: len(normalize_arabic(p)), reverse=True)
            alternation = "|".join(_phrase_regex(p) for p in ordered)
            # Optional attached proclitic (و / ب / ف) before the phrase, e.g. "بطابوقة على صدري".
            exact_pattern = re.compile(
                rf"(?<![{_ARABIC_LETTERS}\d])[وبف]?(?:{alternation})", re.IGNORECASE
            )
            phrase_stems = [
                [t.stem for t in _content_tokens(normalize_arabic(p))] for p in phrases
            ]
            phrase_bigrams = tuple(frozenset(_bigrams(stems)) for stems in phrase_stems)
            leading_bigrams = frozenset(
                (stems[0], stems[1]) for stems in phrase_stems if len(stems) >= 2
            )
            entries.append(
                _LexiconEntry(
                    slang_id=str(record["slang_id"]),
                    category=SymptomCategory(record["category"]),
                    clinical_term_en=str(record["clinical_term_en"]),
                    clinical_term_ar=str(record["clinical_term_ar"]),
                    is_red_flag=bool(record.get("is_red_flag", False)),
                    recommended_specialty=str(record.get("recommended_specialty", "")),
                    linked_doc_ids=tuple(record.get("linked_doc_ids", [])),
                    exact_pattern=exact_pattern,
                    phrase_bigrams=phrase_bigrams,
                    leading_bigrams=leading_bigrams,
                )
            )
        return tuple(entries)

    @staticmethod
    def _build_cue_index(
        entries: tuple[_LexiconEntry, ...],
    ) -> dict[tuple[str, str], tuple[_Cue, ...]]:
        owners: dict[tuple[str, str], set[int]] = defaultdict(set)
        for entry_idx, entry in enumerate(entries):
            for bigrams in entry.phrase_bigrams:
                for bigram in bigrams:
                    owners[bigram].add(entry_idx)
        index: dict[tuple[str, str], tuple[_Cue, ...]] = {}
        for bigram, entry_ids in owners.items():
            if len(entry_ids) > _MAX_CUE_ENTRY_FREQUENCY:
                continue
            base_weight = _CUE_WEIGHTS[len(entry_ids)]
            index[bigram] = tuple(
                _Cue(
                    entry_idx=entry_idx,
                    match_weight=(
                        max(base_weight, _LEADING_CUE_WEIGHT)
                        if bigram in entries[entry_idx].leading_bigrams
                        else base_weight
                    ),
                    evidence_weight=base_weight,
                )
                for entry_idx in sorted(entry_ids)
            )
        return index

    def normalize(self, text: str) -> NormalizationResult:
        """Find Egyptian slang expressions in a PII-scrubbed complaint and map them to clinical terms."""
        started = time.perf_counter()
        if not isinstance(text, str) or not text.strip():
            return NormalizationResult(input_text=text if isinstance(text, str) else "", normalized_text="")

        normalized = normalize_arabic(text)
        matches: list[tuple[float, SlangMatch]] = []
        exact_entries: set[int] = set()

        for entry_idx, entry in enumerate(self._entries):
            found = entry.exact_pattern.search(normalized)
            if found is None:
                continue
            exact_entries.add(entry_idx)
            matches.append(
                (
                    float("inf"),
                    self._build_match(entry, normalized, found.start(), found.end(), MatchType.EXACT, 1.0),
                )
            )

        for entry_idx, candidate in self._score_partial(normalized).items():
            if entry_idx in exact_entries or candidate.score < self.min_partial_score:
                continue
            entry = self._entries[entry_idx]
            # Confidence grows with either phrase coverage or the number of distinctive cues
            # (evidence 1 -> 0.5, 1.5 -> 0.65, 2 -> 0.75), so long lexicon phrases paraphrased
            # by several distinctive cues are not under-rated.
            coverage = max(
                (
                    len(candidate.matched_bigrams & bigrams) / len(bigrams)
                    for bigrams in entry.phrase_bigrams
                    if bigrams
                ),
                default=0.0,
            )
            evidence = 1.0 - 0.5**candidate.evidence
            confidence = round(min(_MAX_PARTIAL_CONFIDENCE, max(coverage, evidence)), 3)
            matches.append(
                (
                    candidate.score,
                    self._build_match(
                        entry, normalized, candidate.start, candidate.end, MatchType.PARTIAL, confidence
                    ),
                )
            )

        # Strongest evidence first (exact, then cue score), ties broken by position in the text.
        matches.sort(key=lambda item: (-item[0], item[1].start))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return NormalizationResult(
            input_text=text,
            normalized_text=normalized,
            matches=tuple(match for _, match in matches),
            elapsed_ms=elapsed_ms,
        )

    def _score_partial(self, normalized: str) -> dict[int, _PartialCandidate]:
        tokens = _content_tokens(normalized)
        candidates: dict[int, _PartialCandidate] = {}
        for left, right in zip(tokens, tokens[1:]):
            bigram = (left.stem, right.stem)
            for cue in self._cue_index.get(bigram, ()):
                candidate = candidates.setdefault(cue.entry_idx, _PartialCandidate())
                if bigram in candidate.matched_bigrams:
                    continue
                candidate.matched_bigrams.add(bigram)
                candidate.score += cue.match_weight
                candidate.evidence += cue.evidence_weight
                if candidate.start < 0:
                    candidate.start = left.start
                candidate.end = max(candidate.end, right.end)
        return candidates

    @staticmethod
    def _build_match(
        entry: _LexiconEntry,
        normalized: str,
        start: int,
        end: int,
        match_type: MatchType,
        confidence: float,
    ) -> SlangMatch:
        return SlangMatch(
            slang_id=entry.slang_id,
            matched_text=normalized[start:end],
            match_type=match_type,
            confidence=confidence,
            clinical_term_en=entry.clinical_term_en,
            clinical_term_ar=entry.clinical_term_ar,
            category=entry.category,
            is_red_flag=entry.is_red_flag,
            recommended_specialty=entry.recommended_specialty,
            linked_doc_ids=entry.linked_doc_ids,
            negated=_is_negated(normalized, start),
            start=start,
            end=end,
        )


def _bigrams(stems: list[str]) -> set[tuple[str, str]]:
    return set(zip(stems, stems[1:]))


def _is_negated(normalized: str, start: int) -> bool:
    window = normalized[max(0, start - _NEGATION_WINDOW_CHARS) : start]
    # The window may cut a word in half; prepend a space so the anchored regex still works.
    return bool(_NEGATION_PREFIX.search(" " + window if not window.startswith(" ") else window))


@lru_cache(maxsize=1)
def get_dialect_normalizer() -> DialectNormalizer:
    """Process-wide normalizer loaded from the default lexicon (loaded once, then cached)."""
    return DialectNormalizer()


def normalize_dialect(text: str) -> NormalizationResult:
    """Normalize a PII-scrubbed complaint with the shared in-memory lexicon."""
    return get_dialect_normalizer().normalize(text)

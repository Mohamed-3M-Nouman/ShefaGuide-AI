"""Deterministic PII/PHI scrubber for Egyptian Arabic patient inputs."""

from __future__ import annotations

import re

REDACTED_TOKEN: str = "[REDACTED]"

# 1. Egyptian 14-digit National ID (starts with century digit 2 or 3, followed by YYMMDD, governorate, etc.)
# Also catches general 14-digit continuous numbers to ensure zero PHI leakage.
EGYPTIAN_NATIONAL_ID_PATTERN: re.Pattern[str] = re.compile(
    r"(?<!\d)[23]\d{13}(?!\d)|(?<!\d)\d{14}(?!\d)"
)

# 2. Egyptian mobile phone numbers:
# Supports optional +20 or 0020 or 20 prefix, optional separators, and 01[0125]XXXXXXXX
EGYPTIAN_PHONE_PATTERN: re.Pattern[str] = re.compile(
    r"(?<!\d)(?:(?:\+|00)?20[\s\-]?)?0?1[0125](?:[\s\-]?\d){8}(?!\d)"
)

# 3. Email addresses
EMAIL_PATTERN: re.Pattern[str] = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# 4. Common Arabic & Egyptian self-identification name patterns:
# e.g., "أنا اسمي أحمد محمد", "اسمي منى علي", "أنا مدام سلوى حسن", "اسمي الحاج سيد إبراهيم"
# Stops before common symptom/clause conjunctions or punctuation.
_STOP_WORDS: str = (
    r"وعندي|عندي|وأنا|وانا|حاسس|حاسة|بعاني|أعاني|اعاني|شغال|ساكن|عمري|سني|رقمي|ورقمي|ورقم|"
    r"تليفوني|وتليفوني|وموبايلي|موبايلي|والبطاقة|والرقم|الرقم|بشتكي|أشتكي|اشتكي|من|بقالي|"
    r"محتاج|عايز|عايزة|حامل|مريض|مريضة|باخد|بآخد|تعبان|تعبانة|مش|في|مساعد"
)

_HONORIFICS: str = (
    r"مدام|الحاج|الحاجة|الأستاذ|الاستاذ|الكابتن|مهندس|المهندس|دكتور|الدكتور"
)

ARABIC_NAME_INTRO_PATTERN: re.Pattern[str] = re.compile(
    rf"(?P<prefix>(?:^|(?<=[\s،,]))(?:(?:أنا|انا)\s+(?:اسمي|إسمي|المريض|المريضة)|(?:اسمي|إسمي)|الاسم\s*[:\-]?|(?:أنا|انا)(?=\s+(?:{_HONORIFICS})\b))\s+)"
    rf"(?P<name>(?:(?:{_HONORIFICS})\s+)?(?:(?!(?:{_STOP_WORDS})\b)[\u0621-\u064A]+(?:\s+(?!(?:{_STOP_WORDS})\b)[\u0621-\u064A]+){{0,2}}))"
)

ENGLISH_NAME_INTRO_PATTERN: re.Pattern[str] = re.compile(
    r"(?P<prefix>\b(?:my\s+name\s+is|i\s+am\s+patient)\s+)"
    r"(?P<name>[A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
    re.IGNORECASE,
)


def contains_pii(text: str) -> bool:
    """Return True if the text contains any detectable PII/PHI pattern."""
    if not text:
        return False
    return bool(
        EGYPTIAN_NATIONAL_ID_PATTERN.search(text)
        or EGYPTIAN_PHONE_PATTERN.search(text)
        or EMAIL_PATTERN.search(text)
        or ARABIC_NAME_INTRO_PATTERN.search(text)
        or ENGLISH_NAME_INTRO_PATTERN.search(text)
    )


def scrub_pii(text: str) -> str:
    """Scrub Egyptian National IDs, phone numbers, emails, and self-identified names with `[REDACTED]`."""
    if not text:
        return text

    scrubbed = text

    # Scrub 14-digit National IDs first so parts of them aren't matched as phone numbers
    scrubbed = EGYPTIAN_NATIONAL_ID_PATTERN.sub(REDACTED_TOKEN, scrubbed)

    # Scrub Egyptian mobile phone numbers
    scrubbed = EGYPTIAN_PHONE_PATTERN.sub(REDACTED_TOKEN, scrubbed)

    # Scrub Email addresses
    scrubbed = EMAIL_PATTERN.sub(REDACTED_TOKEN, scrubbed)

    # Scrub Arabic name introductions while preserving the introductory prefix
    scrubbed = ARABIC_NAME_INTRO_PATTERN.sub(rf"\g<prefix>{REDACTED_TOKEN}", scrubbed)

    # Scrub English name introductions
    scrubbed = ENGLISH_NAME_INTRO_PATTERN.sub(rf"\g<prefix>{REDACTED_TOKEN}", scrubbed)

    return scrubbed

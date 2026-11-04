"""Deterministic input validator for prompt injection and direct medication/prescription requests."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RejectionReason(str, Enum):
    """Reason code for input validation outcome."""

    NONE = "none"
    PROMPT_INJECTION = "prompt_injection"
    MEDICATION_PRESCRIPTION_REQUEST = "medication_prescription_request"
    EMPTY_OR_INVALID = "empty_or_invalid"


class ValidationResult(BaseModel):
    """Structured result returned by the deterministic input safety validator."""

    model_config = ConfigDict(extra="forbid")

    is_safe: bool = Field(..., description="True when the input is safe to process.")
    rejection_flag: bool = Field(
        ..., description="True when the input must be rejected immediately."
    )
    reason: RejectionReason = Field(default=RejectionReason.NONE)
    matched_pattern: str | None = Field(default=None)
    safe_response_ar: str | None = Field(
        default=None,
        description="Pre-approved safe Arabic response to return when rejection_flag is True.",
    )


SAFE_INJECTION_REJECTION_AR: str = (
    "عذراً، لا يمكنني معالجة هذا الطلب. أنا مساعد ذكي مخصص للتوجيه الطبي المبدئي فقط "
    "وتحديد التخصص الطبي المناسب بناءً على الأعراض."
)

SAFE_MEDICATION_REJECTION_AR: str = (
    "عذراً، لا يُسمح لي بوصف الأدوية أو تحديد الجرعات الدوائية (مثل المضادات الحيوية أو المسكنات). "
    "وصف العلاج يتطلب فحصاً طبياً مباشراً من قِبل طبيب مختص حفاظاً على سلامتك."
)

PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above|safety)\s+(?:instructions|guardrails|rules)", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior|system)\s+(?:instructions|prompts)", re.IGNORECASE),
    re.compile(r"(?:you\s+are\s+now\s+(?:in\s+)?|وضع\s+المطور|developer\s+mode|\bdan\b|unrestricted)", re.IGNORECASE),
    re.compile(r"(?:reveal\s+(?:your\s+)?system\s+prompt|system\s+prompt|التعليمات\s+البرمجية\s+السرية)", re.IGNORECASE),
    re.compile(r"system\s*override", re.IGNORECASE),
    re.compile(r"(?:انسى|انسي|إنسى|تجاهل)\s+(?:كل\s+)?(?:التعليمات|الأوامر|القواعد)(?:\s+السابقة)?", re.IGNORECASE),
    re.compile(r"(?:انسى|انسي|إنسى)\s+(?:إنك|انك)\s+ذكاء\s+اصطناعي", re.IGNORECASE),
    re.compile(r"(?:تخطى|أتخطى|اتخطى)\s+(?:كل\s+)?(?:قيود|قواعد|فلتر)\s+(?:الأمان|النظام|الطوارئ)", re.IGNORECASE),
    re.compile(r"تصرف\s+كأنك\s+(?:طبيب\s+بشر[يي]|صيدلي)", re.IGNORECASE),
    re.compile(r"اعرض\s+(?:لي\s+)?تعليمات\s+النظام", re.IGNORECASE),
)

MEDICATION_REQUEST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:اكتبلي|إكتبلي|اكتب\s+لي|إكتب\s+لي|اكتب\s+|اوصفلي|إوصفلي|اوصف\s+لي|رشحلي|اديني|إديني|احسبلي|إحسبلي|حددلي)\s+"
        r"(?:مضاد\s+حيوي|دواء|دوا|علاج|روشتة|مسكن|حقنة|حقن|برشام|جرعة|الجرعة|تشخيص\s+نهائي)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:عايز|عايزة|محتاج|محتاجة|قولي)\s+(?:فوراً\s+)?(?:اسم\s+|جرعة\s+|آخد\s+|اخد\s+)?"
        r"(?:مضاد\s+حيوي|روشتة|دواء\s+لـ?|برشام\s+لـ?|منوم\s+قوي|نيكسيوم)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:ما\s+هي\s+|إيه\s+هي\s+|ايه\s+هي\s+|كم\s+|كام\s+|احسبلي\s+|اكتبلي\s+|عايز\s+)?جرعة\s+"
        r"(?:دواء|الدواء|المضاد\s+الحيوي|أوجمنتين|بانادول|بروفين|كتافلام|شراب|فلاجيل|ليرولين|جابابنتين|نيكسيوم|حقن)",
        re.IGNORECASE,
    ),
    re.compile(r"\bجرعة\s+دواء\b", re.IGNORECASE),
    re.compile(r"(?:آخد|اخد|أخذ)\s+(?:منه\s+)?(?:كام\s+(?:قرص|كبسولة|ملجم|حباية|شريط)|قرصين)", re.IGNORECASE),
    re.compile(r"الجرعة\s+كام\s+قرص", re.IGNORECASE),
    re.compile(
        r"\b(?:prescribe\s+(?:me|the\s+exact)|what\s+antibiotic\s+should\s+i\s+take|give\s+me\s+a\s+prescription|medication\s+dosage\s+for)\b",
        re.IGNORECASE,
    ),
)


def validate_user_input(text: str) -> ValidationResult:
    """Validate user input for prompt injection and direct medication/prescription requests."""
    if not text or not text.strip():
        return ValidationResult(
            is_safe=False,
            rejection_flag=True,
            reason=RejectionReason.EMPTY_OR_INVALID,
            matched_pattern="empty_input",
            safe_response_ar=SAFE_INJECTION_REJECTION_AR,
        )

    normalized = text.strip()

    for pattern in PROMPT_INJECTION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return ValidationResult(
                is_safe=False,
                rejection_flag=True,
                reason=RejectionReason.PROMPT_INJECTION,
                matched_pattern=match.group(0),
                safe_response_ar=SAFE_INJECTION_REJECTION_AR,
            )

    for pattern in MEDICATION_REQUEST_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return ValidationResult(
                is_safe=False,
                rejection_flag=True,
                reason=RejectionReason.MEDICATION_PRESCRIPTION_REQUEST,
                matched_pattern=match.group(0),
                safe_response_ar=SAFE_MEDICATION_REJECTION_AR,
            )

    return ValidationResult(
        is_safe=True,
        rejection_flag=False,
        reason=RejectionReason.NONE,
        matched_pattern=None,
        safe_response_ar=None,
    )

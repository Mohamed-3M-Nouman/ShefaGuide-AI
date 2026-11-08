"""Strict Pydantic v2 API contracts and ethical guardrails for ShefaGuide AI."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum, IntEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

DEFAULT_DISCLAIMER_AR: str = (
    "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر "
    "أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً."
)

# Forbidden definitive diagnostic formulations and medication/dosage terms in rationale_ar
FORBIDDEN_DIAGNOSIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"تشخيصك\s+(هو|النهائي|الأكيد)", re.IGNORECASE),
    re.compile(r"أنت\s+مصاب\s+بـ?", re.IGNORECASE),
    re.compile(r"تم\s+تشخيصك", re.IGNORECASE),
    re.compile(r"من\s+المؤكد\s+إصابتك", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+diagnosed\s+with\b", re.IGNORECASE),
    re.compile(r"\bdefinitive\s+diagnosis\b", re.IGNORECASE),
)

FORBIDDEN_MEDICATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Explicit dosages and prescription directives
    re.compile(r"\b\d+\s*(ملجم|مجم|جرام|مل|قرص|أقراص|كبسولة|كبسولات|mg|ml|mcg|g)\b", re.IGNORECASE),
    re.compile(r"(قرص|كبسولة|معلقة)\s+كل\s+\d*\s*(ساعات|ساعة|يوم|أيام)", re.IGNORECASE),
    re.compile(r"(خذ|تناول|استخدم)\s+(دواء|علاج|مضاد\s+حيوي|مسكن)", re.IGNORECASE),
    # Common Egyptian brand/generic medications that should never be prescribed in triage rationale
    re.compile(
        r"(أوجمنتين|اوجمنتين|كونجستال|بانادول|باراسيتامول|بروفين|إيبوبروفين|ايبوبروفين|"
        r"كتافلام|فولتارين|أزيثرومايسين|ازيثرومايسين|سيبروفلوكساسين|أموكسيسيلين|اموكسيسيلين|"
        r"أنتينال|انتينال|فلاجيل|أوميبرازول|اوميبرازول|أسبوسيد|اسبوسيد|"
        r"\baugmentin\b|\bpanadol\b|\bparacetamol\b|\bibuprofen\b|\bcataflam\b|\bamoxicillin\b|"
        r"\bazithromycin\b|\bciprofloxacin\b|\bflagyl\b|\bantenal\b|\bomeprazole\b)",
        re.IGNORECASE,
    ),
)


class SymptomCategory(str, Enum):
    """High-level clinical symptom taxonomy for initial routing."""

    CARDIOPULMONARY = "cardiopulmonary"
    NEUROLOGICAL_ENT_OPHTH = "neurological_ent_ophth"
    GASTROINTESTINAL = "gastrointestinal"
    MUSCULOSKELETAL = "musculoskeletal"
    SYSTEMIC_FEVER_DERM = "systemic_fever_derm"
    UNKNOWN = "unknown"


class UrgencyLevel(IntEnum):
    """Triage urgency ordered monotonically for the Supremacy Rule `max(rule, llm)`."""

    ROUTINE_SPECIALIST = 1
    URGENT_SPECIALIST = 2
    AMBIGUOUS_SEE_DOCTOR = 3
    EMERGENCY_ESCALATION = 4

    # Backward-compatible integer aliases
    ROUTINE_1 = 1
    URGENT_2 = 2
    URGENT_3 = 3
    EMERGENCY_4 = 4


class SourceCitation(BaseModel):
    """Authoritative clinical guideline citation backing a triage recommendation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    doc_id: str = Field(..., min_length=1, description="Unique document chunk identifier in corpus.")
    source: Literal["WHO", "NHS", "Mayo Clinic"] = Field(
        ..., description="Approved medical knowledge source."
    )
    title: str = Field(..., min_length=1, description="Guideline title.")
    url: HttpUrl | str = Field(..., min_length=1, description="Canonical URL or reference URI.")
    snippet: str = Field(..., min_length=1, description="Relevant clinical excerpt.")


class TriageRequest(BaseModel):
    """Incoming patient triage request payload."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(..., min_length=1, description="Unique conversation session identifier.")
    user_input: str = Field(
        ...,
        min_length=2,
        max_length=1500,
        description="Patient symptom description in Egyptian Arabic or Standard Arabic.",
    )
    input_mode: Literal["text", "voice"] = Field(
        default="text", description="Input modality (text or transcribed voice)."
    )


class TriageResponse(BaseModel):
    """Strictly validated preliminary triage output and specialist referral."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(..., min_length=1)
    urgency_level: UrgencyLevel
    recommended_specialty: str = Field(..., min_length=1)
    symptom_category: SymptomCategory
    rationale_ar: str = Field(
        ...,
        min_length=5,
        description=(
            "Plain Arabic/Egyptian explanation — MUST NOT contain definitive disease diagnosis "
            "or medication names/dosages."
        ),
    )
    clarifying_questions: list[str] = Field(default_factory=list)
    negated_red_flags: list[str] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    disclaimer_ar: str = Field(default=DEFAULT_DISCLAIMER_AR)
    escalation_triggered: bool

    @field_validator("rationale_ar")
    @classmethod
    def validate_rationale_safety(cls, value: str) -> str:
        """Ensure rationale_ar does not issue definitive diagnoses or prescribe medications/dosages."""
        if not value or not value.strip():
            raise ValueError("rationale_ar must not be empty.")

        for pattern in FORBIDDEN_DIAGNOSIS_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "Ethical contract violation: rationale_ar must not contain a definitive disease diagnosis."
                )

        for pattern in FORBIDDEN_MEDICATION_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "Ethical contract violation: rationale_ar must not contain medication names or dosages."
                )

        return value

    @field_validator("disclaimer_ar", mode="before")
    @classmethod
    def validate_disclaimer_not_empty(cls, value: str | None) -> str:
        """Ensure disclaimer_ar is never empty; raise ValueError if explicitly blank."""
        if value is None:
            return DEFAULT_DISCLAIMER_AR
        if isinstance(value, str) and not value.strip():
            raise ValueError("disclaimer_ar must never be empty.")
        return value

    @model_validator(mode="after")
    def validate_citations_and_escalation(self) -> TriageResponse:
        """Enforce citation requirement for specialist referrals and consistency on emergency escalation."""
        if self.urgency_level in (
            UrgencyLevel.ROUTINE_SPECIALIST,
            UrgencyLevel.URGENT_SPECIALIST,
        ):
            if len(self.citations) < 1:
                raise ValueError(
                    "citations must contain at least 1 SourceCitation when urgency_level is "
                    "ROUTINE_SPECIALIST or URGENT_SPECIALIST."
                )

        if self.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION and not self.escalation_triggered:
            raise ValueError(
                "escalation_triggered must be True when urgency_level is EMERGENCY_ESCALATION."
            )

        return self


# ===========================================================================
# Internal Supervisor Dashboard & Zero-PHI Audit Schemas (FR-11, FR-12)
# ===========================================================================


class EscalationItem(BaseModel):
    """Zero-PHI escalation alert for internal supervisor dashboard."""

    model_config = ConfigDict(extra="ignore")

    id: str
    audit_log_id: str
    session_id: str
    created_at: datetime | str
    symptom_category: str
    detected_red_flags: list[str] = Field(default_factory=list)
    scrubbed_summary: str | None = None
    status: str
    acknowledged_at: datetime | str | None = None
    resolved_at: datetime | str | None = None


class EscalationListResponse(BaseModel):
    """Response payload containing list of Zero-PHI escalation alerts."""

    model_config = ConfigDict(extra="ignore")

    items: list[EscalationItem] = Field(default_factory=list)
    count: int = 0


class EscalationUpdateRequest(BaseModel):
    """Payload to transition an escalation status."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["acknowledged", "resolved"]


class AuditLogItem(BaseModel):
    """Zero-PHI audit log entry for clinical interaction audit trail."""

    model_config = ConfigDict(extra="ignore")

    id: str
    session_id: str
    created_at: datetime | str
    scrubbed_input: str
    symptom_category: str
    urgency_level: int
    recommended_specialty: str | None = None
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    escalation_triggered: bool = False
    latency_ms: float | None = None


class AuditLogsResponse(BaseModel):
    """Response payload containing audit log entries and summary metrics."""

    model_config = ConfigDict(extra="ignore")

    items: list[AuditLogItem] = Field(default_factory=list)
    total_count: int = 0
    escalated_count: int = 0
    avg_latency_ms: float = 0.0

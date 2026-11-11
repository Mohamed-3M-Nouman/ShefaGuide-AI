"""Typed state definition for the ShefaGuide AI LangGraph triage state machine."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.schemas.triage import (
    SourceCitation,
    SymptomCategory,
    TriageResponse,
    UrgencyLevel,
)


class TriageState(TypedDict, total=False):
    """Full lifecycle state carried across LangGraph triage nodes."""

    session_id: str
    raw_input: str
    input_mode: Literal["text", "voice"]
    scrubbed_input: str
    current_turn_scrubbed: str
    conversation_history: list[str]
    clarification_count: int
    max_clarification_reached: bool
    execution_latency_ms: float
    pii_redacted_types: list[str]
    is_valid_input: bool
    rejection_reason_ar: str | None
    normalized_input: str
    matched_slang_terms: list[dict[str, Any]]
    rule_urgency: UrgencyLevel
    red_flags_detected: list[str]
    negated_red_flags: list[str]
    primary_category: SymptomCategory
    linked_doc_ids: list[str]
    retrieved_citations: list[SourceCitation]
    llm_urgency: UrgencyLevel
    final_urgency: UrgencyLevel
    recommended_specialty: str
    rationale_ar: str
    clarifying_questions: list[str]
    escalation_triggered: bool
    route_taken: Literal[
        "fast_path_emergency",
        "safe_rejection",
        "clinical_assessment",
        "safe_fallback",
        "max_clarification_fallback",
    ]
    response: TriageResponse

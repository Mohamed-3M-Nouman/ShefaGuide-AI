"""LangGraph State Machine & Deterministic Fast-Path for ShefaGuide AI."""

from __future__ import annotations

import importlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.session_store import (
    MAX_CLARIFICATION_TURNS,
    TURN_SEPARATOR,
    session_store,
)
from app.agent.state import TriageState
from app.safety.pii_scrubber import (
    ARABIC_NAME_INTRO_PATTERN,
    EGYPTIAN_NATIONAL_ID_PATTERN,
    EGYPTIAN_PHONE_PATTERN,
    EMAIL_PATTERN,
    ENGLISH_NAME_INTRO_PATTERN,
    scrub_pii,
)
from app.safety.red_flags import (
    _NEGATION_PREFIX,
    apply_supremacy_rule,
    evaluate_red_flags,
    normalize_arabic,
)
from app.safety.validator import validate_user_input
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SourceCitation,
    SymptomCategory,
    TriageRequest,
    TriageResponse,
    UrgencyLevel,
)
from app.services.triage_service import (
    create_fallback_triage_response,
    get_default_citation,
)

logger = logging.getLogger("shefaguide.agent")

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
SLANG_JSON_PATH: Path = PROJECT_ROOT / "data" / "egyptian_medical_slang.json"
CORPUS_CHUNKS_PATH: Path = PROJECT_ROOT / "data" / "corpus" / "medical_guidelines_chunks.json"

EMERGENCY_SPECIALTY_AR: str = (
    "طوارئ المستشفى والعناية المركزة فوراً (قسم القلب والصدر والمخ والأعصاب والسكتة الدماغية "
    "والعيون والرمد والجهاز الهضمي والمناظير والجراحة العامة وجراحة المخ والأعصاب والعمود الفقري "
    "وجراحة العظام والكسور والروماتيزم والباطنة والحميات والحساسية والجلدية)"
)

REJECTION_SPECIALTY_AR: str = (
    "طبيب مختص (أمراض صدرية / عظام وروماتيزم / أطفال وجهاز هضمي / مخ وأعصاب وأنف وأذن / جلدية وحساسية / عيون / باطنة)"
)

MAX_CLARIFICATION_SPECIALTY_AR: str = "طب الأسرة / طوارئ الباطنة العامة (تقييم طبي مباشر)"

MAX_CLARIFICATION_RATIONALE_AR: str = (
    "بعد عدة جولات من الأسئلة التوضيحية ما زالت الأعراض غير محسومة وتحتاج إلى فحص إكلينيكي مباشر. "
    "يُنصح بمراجعة الطبيب فوراً لإجراء الكشف الطبي المباشر وتقييم حالتك بدقة، "
    "وفي حال ظهور أي علامات خطورة جديدة توجه إلى أقرب طوارئ أو اتصل بالإسعاف (123)."
)


def _merge_unique(base: list[str] | tuple[str, ...], extra: list[str] | tuple[str, ...]) -> list[str]:
    """Order-preserving union of two string sequences."""
    merged = list(base)
    for item in extra:
        if item not in merged:
            merged.append(item)
    return merged


def _load_slang_index() -> list[dict[str, Any]]:
    """Pre-load and normalize `data/egyptian_medical_slang.json` for <15ms in-memory lookup."""
    if not SLANG_JSON_PATH.exists():
        return []
    try:
        raw: Any = json.loads(SLANG_JSON_PATH.read_text(encoding="utf-8"))
        entries: list[dict[str, Any]] = raw if isinstance(raw, list) else raw.get("entries", [])
        indexed: list[dict[str, Any]] = []
        for entry in entries:
            phrases = entry.get("egyptian_phrases", [])
            norm_phrases = [normalize_arabic(p) for p in phrases if p and p.strip()]
            indexed.append({**entry, "_norm_phrases": norm_phrases})
        return indexed
    except Exception:
        return []


def _load_corpus_chunks() -> list[dict[str, Any]]:
    """Pre-load `data/corpus/medical_guidelines_chunks.json` for fast local fallback retrieval."""
    if not CORPUS_CHUNKS_PATH.exists():
        return []
    try:
        raw: Any = json.loads(CORPUS_CHUNKS_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


_SLANG_INDEX: list[dict[str, Any]] = _load_slang_index()
_CORPUS_CHUNKS: list[dict[str, Any]] = _load_corpus_chunks()


def _detect_pii_types(raw_text: str) -> list[str]:
    """Identify which PII/PHI categories were present before scrubbing (never storing raw PII)."""
    if not raw_text:
        return []
    detected: list[str] = []
    if EGYPTIAN_NATIONAL_ID_PATTERN.search(raw_text):
        detected.append("national_id")
    if EGYPTIAN_PHONE_PATTERN.search(raw_text):
        detected.append("phone")
    if EMAIL_PATTERN.search(raw_text):
        detected.append("email")
    if ARABIC_NAME_INTRO_PATTERN.search(raw_text) or ENGLISH_NAME_INTRO_PATTERN.search(raw_text):
        detected.append("name")
    return detected


def build_safe_fallback_response(
    session_id: str = "fallback-session",
    reason_ar: str | None = None,
) -> TriageResponse:
    """Construct a schema-valid Level 3 fallback response guaranteeing SLO-07."""
    safe_sid = (session_id or "fallback-session").strip() or "fallback-session"
    return create_fallback_triage_response(session_id=safe_sid, rationale_ar=reason_ar)


# ===========================================================================
# LangGraph Nodes
# ===========================================================================


def scrub_and_validate_node(state: TriageState) -> TriageState:
    """Node 1: Scrub PII/PHI FIRST (SLO-08), then evaluate red flags and input safety."""
    raw_input = state.get("raw_input", "")
    session_id = state.get("session_id", "")
    pii_types = _detect_pii_types(raw_input)

    # SLO-08: scrub first; only the scrubbed turn is ever validated, merged, or stored.
    current_turn_scrubbed = scrub_pii(raw_input)

    # Evaluate deterministic safety validator (prompt injection & medication requests)
    validation = validate_user_input(current_turn_scrubbed)
    if not validation.rejection_flag and raw_input:
        raw_validation = validate_user_input(raw_input)
        if raw_validation.rejection_flag:
            validation = raw_validation

    # Red flags on the current turn alone (guards against cross-turn negation bleed-through)
    rf_current = evaluate_red_flags(current_turn_scrubbed)
    current_has_red_flag = rf_current.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION

    # Multi-turn context merging (FR-10)
    state_count = int(state.get("clarification_count", 0) or 0)
    prior_session = session_store.get_session(session_id) if session_id else None
    prior_history: list[str] = []
    prior_negated: list[str] = []
    if prior_session is not None and (not validation.rejection_flag or current_has_red_flag):
        prior_history = list(prior_session.scrubbed_history)
        prior_negated = list(prior_session.cumulative_negated_red_flags)
        scrubbed_input = TURN_SEPARATOR.join([*prior_history, current_turn_scrubbed])
        clarification_count = max(state_count, prior_session.clarification_count + 1)
    else:
        scrubbed_input = current_turn_scrubbed
        clarification_count = state_count

    conversation_history = [*prior_history, current_turn_scrubbed]
    max_reached = clarification_count >= MAX_CLARIFICATION_TURNS

    # Red flags on the combined multi-turn picture
    rf_combined = (
        evaluate_red_flags(scrubbed_input) if prior_history else rf_current
    )
    combined_has_red_flag = rf_combined.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION
    rf_eval = rf_combined if combined_has_red_flag or not current_has_red_flag else rf_current

    negated_red_flags = _merge_unique(prior_negated, rf_combined.negated_red_flags)
    negated_red_flags = _merge_unique(negated_red_flags, rf_current.negated_red_flags)

    base_update: TriageState = {
        "scrubbed_input": scrubbed_input,
        "current_turn_scrubbed": current_turn_scrubbed,
        "conversation_history": conversation_history,
        "clarification_count": clarification_count,
        "max_clarification_reached": max_reached,
        "pii_redacted_types": pii_types,
    }

    # Precedence Rule: Life-threatening emergencies (on ANY turn) override rejections and clarification
    if current_has_red_flag or combined_has_red_flag:
        matched = _merge_unique(rf_combined.matched_phrases_ar, rf_current.matched_phrases_ar)
        doc_ids = _merge_unique(rf_combined.linked_doc_ids, rf_current.linked_doc_ids)
        return {
            **base_update,
            "is_valid_input": True,
            "rejection_reason_ar": None,
            "rule_urgency": UrgencyLevel.EMERGENCY_ESCALATION,
            "red_flags_detected": matched,
            "negated_red_flags": negated_red_flags,
            "primary_category": rf_eval.primary_category,
            "linked_doc_ids": doc_ids,
        }

    is_valid = not validation.rejection_flag
    rejection_reason = validation.safe_response_ar if validation.rejection_flag else None

    return {
        **base_update,
        "is_valid_input": is_valid,
        "rejection_reason_ar": rejection_reason,
        "rule_urgency": UrgencyLevel.ROUTINE_SPECIALIST,
        "red_flags_detected": [],
        "negated_red_flags": negated_red_flags,
        "primary_category": rf_eval.primary_category,
        "linked_doc_ids": list(rf_eval.linked_doc_ids),
    }


def route_after_validation(state: TriageState) -> str:
    """Conditional Edge 1: Fast-Path to emergency escalation, safe rejection, or dialect normalization."""
    if state.get("rule_urgency") == UrgencyLevel.EMERGENCY_ESCALATION:
        return "mandatory_escalation_node"
    if not state.get("is_valid_input", True):
        return "safe_rejection_node"
    return "normalize_dialect_node"


def normalize_dialect_node(state: TriageState) -> TriageState:
    """Node 2: Normalize Egyptian Arabic medical slang via adapter or <15ms in-memory lookup."""
    scrubbed_input = state.get("scrubbed_input") or scrub_pii(state.get("raw_input", ""))
    norm_text = normalize_arabic(scrubbed_input)

    matched_terms: list[dict[str, Any]] = []
    linked_docs: list[str] = list(state.get("linked_doc_ids", []))
    primary_category: SymptomCategory = state.get("primary_category", SymptomCategory.UNKNOWN)

    # Optional Saturday teammate adapter: app.rag.dialect_normalizer
    teammate_matches: list[dict[str, Any]] | None = None
    try:
        mod = importlib.import_module("app.rag.dialect_normalizer")
        if hasattr(mod, "normalize_egyptian_dialect"):
            res = mod.normalize_egyptian_dialect(scrubbed_input)
            if isinstance(res, list):
                teammate_matches = res
            elif isinstance(res, dict) and isinstance(res.get("matched_terms"), list):
                teammate_matches = res["matched_terms"]
    except ImportError:
        teammate_matches = None
    except Exception as exc:
        logger.warning("Dialect normalizer adapter fallback triggered: %s", exc)
        teammate_matches = None

    if teammate_matches is not None:
        matched_terms = teammate_matches
        for m in matched_terms:
            if primary_category == SymptomCategory.UNKNOWN and m.get("category"):
                try:
                    primary_category = SymptomCategory(m["category"])
                except ValueError:
                    pass
            for doc_id in m.get("linked_doc_ids", []):
                if doc_id not in linked_docs:
                    linked_docs.append(doc_id)
    else:
        for entry in _SLANG_INDEX:
            for norm_phrase in entry.get("_norm_phrases", []):
                if not norm_phrase:
                    continue
                idx = norm_text.find(norm_phrase)
                if idx != -1:
                    preceding = norm_text[max(0, idx - 40) : idx]
                    is_negated = bool(_NEGATION_PREFIX.search(preceding))
                    if is_negated:
                        continue
                    matched_terms.append(
                        {
                            "slang_id": entry["slang_id"],
                            "clinical_term_ar": entry["clinical_term_ar"],
                            "clinical_term_en": entry.get("clinical_term_en", ""),
                            "category": entry["category"],
                            "is_red_flag": bool(entry.get("is_red_flag", False)),
                            "recommended_specialty": entry.get("recommended_specialty", ""),
                            "linked_doc_ids": list(entry.get("linked_doc_ids", [])),
                        }
                    )
                    if primary_category == SymptomCategory.UNKNOWN:
                        try:
                            primary_category = SymptomCategory(entry["category"])
                        except ValueError:
                            pass
                    for doc_id in entry.get("linked_doc_ids", []):
                        if doc_id not in linked_docs:
                            linked_docs.append(doc_id)
                    break

    return {
        "normalized_input": norm_text,
        "matched_slang_terms": matched_terms,
        "linked_doc_ids": linked_docs,
        "primary_category": primary_category,
    }


def deterministic_red_flag_node(state: TriageState) -> TriageState:
    """Node 3: Verify deterministic red-flag status after dialect normalization."""
    scrubbed_input = state.get("scrubbed_input", "")
    rf_eval = evaluate_red_flags(scrubbed_input)

    rule_urgency = state.get("rule_urgency", UrgencyLevel.ROUTINE_SPECIALIST)
    red_flags_detected = list(state.get("red_flags_detected", []))
    negated_red_flags = list(state.get("negated_red_flags", []))
    linked_docs = list(state.get("linked_doc_ids", []))
    primary_category = state.get("primary_category", SymptomCategory.UNKNOWN)

    if rf_eval.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION:
        rule_urgency = UrgencyLevel.EMERGENCY_ESCALATION
        for phrase in rf_eval.matched_phrases_ar:
            if phrase not in red_flags_detected:
                red_flags_detected.append(phrase)
        if primary_category == SymptomCategory.UNKNOWN:
            primary_category = rf_eval.primary_category
        for doc_id in rf_eval.linked_doc_ids:
            if doc_id not in linked_docs:
                linked_docs.append(doc_id)

    for neg in rf_eval.negated_red_flags:
        if neg not in negated_red_flags:
            negated_red_flags.append(neg)

    # Also check if dialect normalization surfaced a non-negated red-flag slang entry
    for term in state.get("matched_slang_terms", []):
        if term.get("is_red_flag"):
            rule_urgency = UrgencyLevel.EMERGENCY_ESCALATION
            clinical_ar = str(term.get("clinical_term_ar", "")).strip()
            if clinical_ar and clinical_ar not in red_flags_detected:
                red_flags_detected.append(clinical_ar)
            for doc_id in term.get("linked_doc_ids", []):
                if doc_id not in linked_docs:
                    linked_docs.append(doc_id)

    return {
        "rule_urgency": rule_urgency,
        "red_flags_detected": red_flags_detected,
        "negated_red_flags": negated_red_flags,
        "linked_doc_ids": linked_docs,
        "primary_category": primary_category,
    }


def route_after_red_flag_check(state: TriageState) -> str:
    """Conditional Edge 2: Route to mandatory escalation if red-flag detected, else retrieve guidelines."""
    if state.get("rule_urgency") == UrgencyLevel.EMERGENCY_ESCALATION:
        return "mandatory_escalation_node"
    return "retrieve_guidelines_node"


def mandatory_escalation_node(state: TriageState) -> TriageState:
    """Fast-Path Node: Zero-LLM emergency escalation (<15ms, SLA <1.5s)."""
    session_id = state.get("session_id", "fallback-session")
    doc_ids = state.get("linked_doc_ids") or ["NHS-CARDIO-001"]
    citations = [get_default_citation(doc_id) for doc_id in doc_ids]

    red_flags = state.get("red_flags_detected") or ["علامات خطورة طبية حادة"]
    matched_summary = "، ".join(red_flags)
    rationale_ar = (
        f"تم رصد علامات خطورة طبية حادة ({matched_summary}). "
        "يجب التوجه فوراً إلى طوارئ المستشفى أو الاتصال بالإسعاف (123) لعمل الفحوصات العاجلة."
    )

    final_urgency = apply_supremacy_rule(
        UrgencyLevel.EMERGENCY_ESCALATION,
        UrgencyLevel.EMERGENCY_ESCALATION,
    )
    primary_category = state.get("primary_category", SymptomCategory.CARDIOPULMONARY)

    response = TriageResponse(
        session_id=session_id,
        urgency_level=final_urgency,
        recommended_specialty=EMERGENCY_SPECIALTY_AR,
        symptom_category=primary_category,
        rationale_ar=rationale_ar,
        clarifying_questions=[],
        negated_red_flags=list(state.get("negated_red_flags", [])),
        citations=citations,
        disclaimer_ar=DEFAULT_DISCLAIMER_AR,
        escalation_triggered=True,
    )

    return {
        "final_urgency": final_urgency,
        "recommended_specialty": EMERGENCY_SPECIALTY_AR,
        "rationale_ar": rationale_ar,
        "clarifying_questions": [],
        "retrieved_citations": citations,
        "escalation_triggered": True,
        "route_taken": "fast_path_emergency",
        "response": response,
    }


def safe_rejection_node(state: TriageState) -> TriageState:
    """Safe Rejection Node: Returns Level 3 TriageResponse on prompt injection or prescription request."""
    session_id = state.get("session_id", "fallback-session")
    rationale_ar = (
        state.get("rejection_reason_ar")
        or "يرجى التوجه لطبيب مختص لتقييم الحالة بشكل آمن ودقيق."
    )
    citations = [get_default_citation("NHS-SYS-004")]
    final_urgency = UrgencyLevel.AMBIGUOUS_SEE_DOCTOR

    response = TriageResponse(
        session_id=session_id,
        urgency_level=final_urgency,
        recommended_specialty=REJECTION_SPECIALTY_AR,
        symptom_category=SymptomCategory.UNKNOWN,
        rationale_ar=rationale_ar,
        clarifying_questions=[],
        negated_red_flags=list(state.get("negated_red_flags", [])),
        citations=citations,
        disclaimer_ar=DEFAULT_DISCLAIMER_AR,
        escalation_triggered=False,
    )

    return {
        "final_urgency": final_urgency,
        "recommended_specialty": REJECTION_SPECIALTY_AR,
        "rationale_ar": rationale_ar,
        "clarifying_questions": [],
        "retrieved_citations": citations,
        "escalation_triggered": False,
        "route_taken": "safe_rejection",
        "response": response,
    }


def retrieve_guidelines_node(state: TriageState) -> TriageState:
    """Node 4: Retrieve authoritative WHO/NHS/Mayo clinical citations via adapter or local corpus."""
    linked_doc_ids = list(state.get("linked_doc_ids", []))
    primary_category = state.get("primary_category", SymptomCategory.UNKNOWN)
    scrubbed_input = state.get("scrubbed_input", "")

    citations: list[SourceCitation] = []

    # Optional Saturday teammate adapter: app.rag.retriever.retrieve_guidelines
    try:
        mod = importlib.import_module("app.rag.retriever")
        if hasattr(mod, "retrieve_guidelines"):
            retrieved = mod.retrieve_guidelines(scrubbed_input)
            if isinstance(retrieved, list) and retrieved:
                for item in retrieved:
                    if isinstance(item, SourceCitation):
                        citations.append(item)
                    elif isinstance(item, dict) and "doc_id" in item:
                        citations.append(get_default_citation(str(item["doc_id"])))
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Retriever adapter fallback triggered: %s", exc)

    if not citations and linked_doc_ids:
        for doc_id in linked_doc_ids:
            citations.append(get_default_citation(doc_id))

    if not citations and primary_category != SymptomCategory.UNKNOWN:
        for chunk in _CORPUS_CHUNKS:
            if chunk.get("category") == primary_category.value:
                citations.append(get_default_citation(str(chunk["doc_id"])))
                break

    return {
        "retrieved_citations": citations,
    }


# Pluggable clinical assessment hook and optional injected LLM for structured tools
ClinicalAssessorHook = Callable[
    [TriageState],
    tuple[SymptomCategory, str, UrgencyLevel, list[SourceCitation], list[str], str | None],
]

_injected_agent_llm: Any | None = None


def set_agent_llm(llm: Any | None) -> None:
    """Configure or reset an injected LLM client for `symptom_severity_tool` and `specialty_mapping_tool`."""
    global _injected_agent_llm
    _injected_agent_llm = llm


def _default_clinical_assessor(
    state: TriageState,
) -> tuple[SymptomCategory, str, UrgencyLevel, list[SourceCitation], list[str], str | None]:
    """Default clinical assessor invoking `symptom_severity_tool` and `specialty_mapping_tool`."""
    from app.agent.tools import assess_with_agent_tools

    return assess_with_agent_tools(state, llm=_injected_agent_llm)


_clinical_assessor_hook: ClinicalAssessorHook = _default_clinical_assessor


def set_clinical_assessor_hook(hook: ClinicalAssessorHook | None) -> None:
    """Configure or reset the clinical assessment hook used by `clinical_assessment_node`."""
    global _clinical_assessor_hook
    _clinical_assessor_hook = hook or _default_clinical_assessor


def clinical_assessment_node(state: TriageState) -> TriageState:
    """Node 5: Assess non-emergency presentation and enforce the Supremacy Rule `max(rule, llm)`."""
    session_id = state.get("session_id", "fallback-session")
    rule_urgency = state.get("rule_urgency", UrgencyLevel.ROUTINE_SPECIALIST)

    category, specialty, llm_urgency, route_citations, questions, custom_rationale = (
        _clinical_assessor_hook(state)
    )

    # Enforce Supremacy Rule: deterministic rule urgency can never be downgraded by LLM urgency
    final_urgency = apply_supremacy_rule(rule_urgency, llm_urgency)

    # Merge retrieved citations with route citations, guaranteeing at least 1 valid citation
    retrieved_citations = list(state.get("retrieved_citations", []))
    seen_doc_ids = {c.doc_id for c in retrieved_citations}
    for rc in route_citations:
        if rc.doc_id not in seen_doc_ids:
            retrieved_citations.append(rc)
            seen_doc_ids.add(rc.doc_id)

    if not retrieved_citations:
        retrieved_citations = [get_default_citation("NHS-SYS-005")]

    # Prefer route citations first so specificity matches exact symptom category expectations
    final_citations = route_citations if route_citations else retrieved_citations

    rationale_ar = custom_rationale or (
        f"بناءً على الأعراض المذكورة، يُنصح بحجز كشف لدى تخصص {specialty} "
        "لإجراء الفحص الإكلينيكي وتقييم الحالة بدقة."
    )
    escalation_triggered = final_urgency == UrgencyLevel.EMERGENCY_ESCALATION

    # Deterministic Max-3-Turns Safety Guardrail (FR-10): stop clarifying, direct to a doctor.
    clarification_count = int(state.get("clarification_count", 0) or 0)
    max_reached = clarification_count >= MAX_CLARIFICATION_TURNS
    route_taken = "clinical_assessment"
    still_unresolved = (
        final_urgency == UrgencyLevel.AMBIGUOUS_SEE_DOCTOR
        or bool(questions)
        or category == SymptomCategory.UNKNOWN
    )
    if max_reached and not escalation_triggered and still_unresolved:
        final_urgency = max(final_urgency, UrgencyLevel.AMBIGUOUS_SEE_DOCTOR)
        questions = []
        specialty = MAX_CLARIFICATION_SPECIALTY_AR
        rationale_ar = MAX_CLARIFICATION_RATIONALE_AR
        route_taken = "max_clarification_fallback"

    response = TriageResponse(
        session_id=session_id,
        urgency_level=final_urgency,
        recommended_specialty=specialty,
        symptom_category=category,
        rationale_ar=rationale_ar,
        clarifying_questions=questions,
        negated_red_flags=list(state.get("negated_red_flags", [])),
        citations=final_citations,
        disclaimer_ar=DEFAULT_DISCLAIMER_AR,
        escalation_triggered=escalation_triggered,
    )

    return {
        "primary_category": category,
        "recommended_specialty": specialty,
        "llm_urgency": llm_urgency,
        "final_urgency": final_urgency,
        "rationale_ar": rationale_ar,
        "clarifying_questions": questions,
        "retrieved_citations": final_citations,
        "escalation_triggered": escalation_triggered,
        "max_clarification_reached": max_reached,
        "route_taken": route_taken,
        "response": response,
    }


# ===========================================================================
# Graph Compilation & Execution Entrypoints
# ===========================================================================


def build_triage_graph() -> Any:
    """Construct and compile the ShefaGuide AI LangGraph `StateGraph(TriageState)`."""
    workflow = StateGraph(TriageState)

    # Register nodes
    workflow.add_node("scrub_and_validate_node", scrub_and_validate_node)
    workflow.add_node("normalize_dialect_node", normalize_dialect_node)
    workflow.add_node("deterministic_red_flag_node", deterministic_red_flag_node)
    workflow.add_node("mandatory_escalation_node", mandatory_escalation_node)
    workflow.add_node("safe_rejection_node", safe_rejection_node)
    workflow.add_node("retrieve_guidelines_node", retrieve_guidelines_node)
    workflow.add_node("clinical_assessment_node", clinical_assessment_node)

    # Entry edge
    workflow.add_edge(START, "scrub_and_validate_node")

    # Conditional Edge 1: Immediate Fast-Path after scrub & validation
    workflow.add_conditional_edges(
        "scrub_and_validate_node",
        route_after_validation,
        {
            "mandatory_escalation_node": "mandatory_escalation_node",
            "safe_rejection_node": "safe_rejection_node",
            "normalize_dialect_node": "normalize_dialect_node",
        },
    )

    # Dialect normalization -> post-normalization red-flag check
    workflow.add_edge("normalize_dialect_node", "deterministic_red_flag_node")

    # Conditional Edge 2: Post-normalization red-flag check
    workflow.add_conditional_edges(
        "deterministic_red_flag_node",
        route_after_red_flag_check,
        {
            "mandatory_escalation_node": "mandatory_escalation_node",
            "retrieve_guidelines_node": "retrieve_guidelines_node",
        },
    )

    # Guideline retrieval -> clinical assessment
    workflow.add_edge("retrieve_guidelines_node", "clinical_assessment_node")

    # Terminal edges
    workflow.add_edge("mandatory_escalation_node", END)
    workflow.add_edge("safe_rejection_node", END)
    workflow.add_edge("clinical_assessment_node", END)

    return workflow.compile()


triage_graph = build_triage_graph()


def _persist_session_turn(request: TriageRequest, final_state: TriageState) -> None:
    """Persist the scrubbed turn + routing metadata (zero PHI) so the next turn can merge context.

    Safe-rejection turns are never stored, so injected/prescription text cannot poison history.
    Persistence failures must never break triage (SLO-07).
    """
    try:
        response = final_state.get("response")
        route_taken = final_state.get("route_taken")
        current_turn = final_state.get("current_turn_scrubbed")
        if (
            not isinstance(response, TriageResponse)
            or route_taken in (None, "safe_rejection")
            or not current_turn
        ):
            return
        session_store.update_session(
            request.session_id,
            current_turn,
            negated_red_flags=final_state.get("negated_red_flags", []),
            urgency=int(final_state.get("final_urgency", response.urgency_level)),
            route_taken=route_taken,
            retrieved_doc_ids=[c.doc_id for c in response.citations],
            red_flags_detected=final_state.get("red_flags_detected", []),
            latency_ms=float(final_state.get("execution_latency_ms", 0.0)),
            clarification_count=int(final_state.get("clarification_count", 0) or 0),
            recommended_specialty=response.recommended_specialty,
            symptom_category=response.symptom_category.value,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Session persistence skipped: %s", exc)


def invoke_triage_graph_state(request: TriageRequest) -> TriageState:
    """Execute the compiled LangGraph state machine and return the full final `TriageState`."""
    initial_state: TriageState = {
        "session_id": request.session_id,
        "raw_input": request.user_input,
        "input_mode": request.input_mode,
    }
    started = time.perf_counter()
    result: TriageState = triage_graph.invoke(initial_state)
    result["execution_latency_ms"] = (time.perf_counter() - started) * 1000.0
    _persist_session_turn(request, result)
    return result


def run_triage_agent_sync(request: TriageRequest) -> TriageResponse:
    """Synchronous entrypoint executing the LangGraph triage state machine with SLO-07 fallback."""
    try:
        final_state = invoke_triage_graph_state(request)
        response = final_state.get("response")
        if isinstance(response, TriageResponse):
            return response
        return build_safe_fallback_response(session_id=request.session_id)
    except Exception as exc:
        logger.error("Unhandled exception in run_triage_agent_sync: %s", exc, exc_info=True)
        return build_safe_fallback_response(session_id=request.session_id)


async def run_triage_agent(request: TriageRequest) -> TriageResponse:
    """Async entrypoint executing the LangGraph triage state machine with SLO-07 fallback."""
    try:
        final_state = invoke_triage_graph_state(request)
        response = final_state.get("response")
        if isinstance(response, TriageResponse):
            return response
        return build_safe_fallback_response(session_id=request.session_id)
    except Exception as exc:
        logger.error("Unhandled exception in run_triage_agent: %s", exc, exc_info=True)
        return build_safe_fallback_response(session_id=request.session_id)

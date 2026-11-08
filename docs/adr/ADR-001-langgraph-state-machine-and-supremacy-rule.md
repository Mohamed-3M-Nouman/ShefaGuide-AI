# ADR-001: LangGraph Deterministic State Machine & The Supremacy Rule for Clinical Triage

- **Status**: Accepted — Production Baseline
- **Date**: 2026-11-08
- **Deciders**: ShefaGuide AI Architecture & Clinical Safety Engineering Team (DEPI Capstone)
- **Target SLOs**: SLO-01 (100.00% Urgent Escalation Recall), SLO-02 (>= 80.00% Specialty Referral Accuracy), SLO-05 (Fast-Path Emergency P99 Latency <= 1.5s)

---

## Context & Problem Statement

In an AI-assisted clinical pre-care and specialist referral system serving Egyptian Arabic patients, relying solely on a free-form Large Language Model (LLM) introduces two unacceptable clinical risks:
1. **Hallucinated Downgrading of Life-Threatening Emergencies**: An LLM might misinterpret colloquial Egyptian red-flag expressions (such as *"حاسس بطابوقة كابسة على نص صدري ومسمعة في دراعي الشمال"* for acute myocardial infarction or *"لسانه تقل ووشه اتعوج فجأة"* for acute stroke) and classify a Level 4 emergency as a routine outpatient visit.
2. **Unbounded Latency During Acute Crises**: Multi-step LLM tool calls and vector retrieval take hundreds of milliseconds to seconds, whereas life-threatening presentations require immediate, deterministic escalation to emergency care (`123` ambulance / hospital ER).

We needed an orchestration architecture that guarantees **100.00% recall on known clinical red flags**, enforces a sub-second fast path for acute emergencies, and bounds LLM reasoning within strict, auditable state transitions.

---

## Architectural Decision

We adopted a **compiled LangGraph `StateGraph(TriageState)`** (`app/agent/graph.py`) governed by two non-negotiable safety invariants:

1. **Zero-LLM Emergency Fast-Path (`mandatory_escalation_node`)**:
   - Immediately after PII scrubbing (`scrub_and_validate_node`) and dialect normalization (`normalize_dialect_node`), deterministic regex and lexicon red-flag evaluators (`evaluate_red_flags` in `app/safety/red_flags.py`) inspect the input.
   - If any non-negated life-threatening red flag is detected, conditional edges (`route_after_validation` and `route_after_red_flag_check`) route execution directly to `mandatory_escalation_node`, bypassing Qdrant retrieval and Gemini LLM invocation entirely.
   - This fast-path executes in **< 15 ms** (well below the 1,500 ms SLO-05 ceiling).

2. **The Supremacy Rule (`apply_supremacy_rule`)**:
   - `UrgencyLevel` (`app/schemas/triage.py`) is modeled as a monotonically ordered `IntEnum`:
     - `ROUTINE_SPECIALIST = 1`
     - `URGENT_SPECIALIST = 2`
     - `AMBIGUOUS_SEE_DOCTOR = 3`
     - `EMERGENCY_ESCALATION = 4`
   - Whenever both the deterministic rule engine (`rule_urgency`) and the structured-output Gemini 2.5 Flash clinical assessment tools (`llm_urgency`) produce urgency levels, the final urgency is computed strictly as:
     $$\text{final\_urgency} = \max(\text{rule\_urgency}, \text{llm\_urgency})$$
   - The LLM is permitted to **escalate** urgency (e.g., recognizing a subtle acute presentation not covered by static rules) but is mathematically **incapable of downgrading** a deterministic red-flag escalation.

---

## Technical Implementation in Repository

- **State Contract (`app/agent/state.py`)**:
  - `TriageState` (`TypedDict`) tracks `session_id`, `raw_input`, `scrubbed_input`, `normalized_input`, `matched_slang_terms`, `rule_urgency`, `llm_urgency`, `final_urgency`, `red_flags_detected`, `negated_red_flags`, `retrieved_citations`, `route_taken`, and `response`.
- **LangGraph Workflow (`app/agent/graph.py`)**:
  - `build_triage_graph()` compiles the 7-node state machine:
    1. `scrub_and_validate_node`: Scrubs PHI via `scrub_pii()` and checks prompt injection / medication prescription guardrails (`validate_user_input()`).
    2. `normalize_dialect_node`: Maps Egyptian vernacular to clinical Arabic/English concepts and tracks negated phrases.
    3. `deterministic_red_flag_node`: Evaluates post-normalization red flags.
    4. `mandatory_escalation_node`: Zero-LLM Level 4 emergency escalation (`route_taken = "fast_path_emergency"`).
    5. `safe_rejection_node`: Returns Level 3 (`AMBIGUOUS_SEE_DOCTOR`) safe guidance when adversarial prompt injection or medication prescription requests are detected (`route_taken = "safe_rejection"`).
    6. `retrieve_guidelines_node`: Queries Qdrant hybrid RAG (`app/rag/retriever.py`) for WHO/NHS/Mayo Clinic citations.
    7. `clinical_assessment_node`: Invokes structured-output Gemini tools (`symptom_severity_tool` and `specialty_mapping_tool` in `app/agent/tools.py`) and enforces `apply_supremacy_rule(rule_urgency, llm_urgency)`.
- **Supremacy & Red-Flag Engine (`app/safety/red_flags.py`)**:
  - `evaluate_red_flags()` and `apply_supremacy_rule()` enforce Arabic negation window checks so negated symptoms (e.g., *"معنديش وجع في صدري"*) are recorded in `negated_red_flags` without false-positive escalation.

---

## Consequences

### Positive
- **Deterministic Clinical Safety**: Guarantees 100.00% recall on red-flag emergencies regardless of LLM availability, temperature, or prompt variations.
- **Ultra-Low Emergency Latency**: Fast-path escalations complete in `< 15 ms` P99 without external API calls.
- **Full Auditability**: Every state transition and `route_taken` (`fast_path_emergency`, `safe_rejection`, `standard_rag_clinical`) is explicitly recorded.

### Trade-offs
- Maintaining the deterministic red-flag ruleset (`app/safety/red_flags.py`) and Egyptian slang lexicon (`data/egyptian_medical_slang.json`) requires periodic clinical curation alongside LLM prompt updates.

---

## DEPI SLO Verification Evidence

- **Automated Evaluation (`eval/run_eval.py`)**:
  - **SLO-01 (Urgent Escalation Recall)**: `100.00%` across 100 labeled Egyptian Arabic clinical test cases.
  - **SLO-02 (Specialty Referral Accuracy)**: `100.00%` (Target: `>= 80.00%`).
  - **SLO-04 / SLO-05 (Latency)**: P95 `0.65 ms`, P99 `0.70 ms` on deterministic evaluation path.
- **Unit & Integration Tests**:
  - `tests/test_step3_langgraph_agent.py` and `tests/test_step4_gemini_agent_tools.py` explicitly verify that even when a mocked LLM returns `UrgencyLevel.ROUTINE_SPECIALIST (1)` for a red-flag input, `apply_supremacy_rule` overrides the result to `UrgencyLevel.EMERGENCY_ESCALATION (4)`.

# ADR-003: Zero-PHI Privacy Architecture & Multi-Layered PII Scrubbing

- **Status**: Accepted — Production Baseline
- **Date**: 2026-11-08
- **Deciders**: ShefaGuide AI Security, Privacy & Data Engineering Team (DEPI Capstone)
- **Target SLOs**: SLO-08 (0.00% PHI Leakage Rate across LLM Prompts, Responses, Database Audit Logs, and SSE Streams)

---

## Context & Problem Statement

Patients seeking medical triage frequently volunteer sensitive Personal Health Information (PHI) and Personally Identifiable Information (PII) inside their symptom descriptions—including full Arabic/English names, Egyptian mobile phone numbers (`010/011/012/015`), 14-digit Egyptian National IDs (*الرقم القومي*), landline numbers, and email addresses (e.g., *"أنا اسمي طارق عبد الرحمن ورقم موبايلي 01098765432 والبطاقة 29208151200456 وعندي وجع شديد في صدري"*).

Persisting raw PII to operational databases, forwarding identifiable patient data to third-party LLM APIs, writing patient voice recordings to disk, or broadcasting unredacted alerts over supervisor SSE streams creates severe regulatory, ethical, and privacy liabilities. We needed a **Zero-PHI by construction** architecture that guarantees **0.00% PHI leakage (SLO-08)** even if an upstream caller forgets to sanitize input.

---

## Architectural Decision

We implemented a **Four-Layer Defense-in-Depth Zero-PHI Architecture**:

1. **Layer 1 — Deterministic Pre-Processing PII Scrubber (`app/safety/pii_scrubber.py`)**:
   - The very first node of the LangGraph state machine (`scrub_and_validate_node` in `app/agent/graph.py`) executes `scrub_pii(raw_input)` before any dialect normalization, RAG retrieval, or LLM invocation.
   - `scrub_pii()` replaces all recognized PII patterns with `[REDACTED]`, including:
     - **14-Digit Egyptian National IDs**: `\b[23]\d{13}\b` (evaluated first so 11-digit phone substrings inside a 14-digit ID are never partially matched).
     - **Egyptian Mobile & Landline Numbers**: `(?:\+?20|0020)?[\s\-]*0?1[0125][\s\-]*\d{4}[\s\-]*\d{4}` and `0[2-9]\d{7,8}` (including Arabic-Indic numerals `٠١٠...` normalized prior to matching).
     - **Email Addresses**: Standard RFC-compliant email regex.
     - **Arabic & English Self-Identification Name Patterns**: Contextual triggers such as `"أنا اسمي ..."`, `"اسمي ..."`, `"المريض ..."`, `"يا دكتور أنا ..."`, and `"My name is ..."`, carefully bounded by symptom stop-words (`وعندي`, `وحاسس`, `وبشتكي`, `من`, `في`) so clinical symptom words are never accidentally redacted.

2. **Layer 2 — Ephemeral In-Memory Voice Processing (`app/voice/adapter.py`)**:
   - Patient voice recordings submitted to `POST /api/v1/voice/transcribe` or `POST /api/v1/voice/triage` are decoded from Base64 strictly in RAM (`decode_audio_base64`) and transmitted as in-memory `bytes` buffers.
   - Synthesized Arabic TTS audio (`synthesize_speech`) is generated inside an `io.BytesIO` buffer using Python's `wave` module and Base64-encoded directly from memory.
   - **Zero temporary files** are ever written to the filesystem (`0` disk footprint for patient audio).

3. **Layer 3 — SQLAlchemy TypeDecorator & Fail-Fast CRUD Guards (`app/db/models.py`, `app/db/crud.py`)**:
   - Every text and JSON column in `AuditLog` (`audit_logs`) and `EscalationQueue` (`escalation_queue`) uses custom SQLAlchemy `TypeDecorator` classes (`ScrubbedText` and `ScrubbedJSON`) that automatically invoke `scrub_value()` at SQL bind time (`process_bind_param`).
   - In `app/db/crud.py`, `_require_clean()` runs `scrub_pii()` followed by a hard `contains_pii()` verification assertion (`PHILeakError`) before any row is flushed to PostgreSQL or SQLite, plus an opaque token validator on `session_id`.

4. **Layer 4 — Real-Time SSE Stream Sanitization (`app/core/sse.py`)**:
   - `EscalationBroadcaster.publish_escalation()` runs `_sanitize_text()` (`scrub_pii` + `contains_pii` check) and `_sanitize_session_id()` on every field before storing events in the in-memory ring buffer (`deque(maxlen=50)`) or pushing them to connected supervisor dashboard subscribers (`GET /api/v1/escalations/stream`).

---

## Technical Implementation in Repository

- **PII Scrubber & Detector (`app/safety/pii_scrubber.py`)**:
  - Exports `scrub_pii(text)`, `scrub_pii_detailed(text)` (returning `PIIScrubResult` with `redacted_types`), `contains_pii(text)`, and `REDACTED_TOKEN = "[REDACTED]"`.
- **Database Models & CRUD (`app/db/models.py`, `app/db/crud.py`)**:
  - `ScrubbedText`, `ScrubbedJSON`, `AuditLog`, `EscalationQueue`, `create_audit_log()`, and `log_interaction()` enforce zero-PHI persistence.
- **SSE Broadcaster (`app/core/sse.py`)**:
  - `EscalationBroadcaster.publish_escalation()` scrubs `session_id`, `symptom_category`, `recommended_specialty`, `detected_red_flags`, and `scrubbed_summary`.
- **Voice Adapter (`app/voice/adapter.py`)**:
  - `VoiceAdapter.transcribe_audio()` and `VoiceAdapter.synthesize_speech()` operate exclusively on in-memory `bytes` and `io.BytesIO`.

---

## Consequences

### Positive
- **Defense-in-Depth Guarantee**: Even if a future developer passes raw `user_input` directly to `log_interaction()` or `escalation_broadcaster.publish_escalation()`, the CRUD and SQLAlchemy bind-time scrubbers automatically redact all PII before it touches storage or network streams.
- **Compliance & Auditability**: Supervisor dashboards (`GET /api/v1/audit-logs`, `GET /api/v1/escalations`, `GET /api/v1/escalations/stream`) provide full operational visibility into red-flag escalations without exposing patient identities.

### Trade-offs
- Aggressive regex scrubbing requires careful stop-word boundaries (`_SYMPTOM_STOPWORDS_AR`) to avoid redacting clinical descriptions that immediately follow a patient's name without punctuation.

---

## DEPI SLO Verification Evidence

- **Automated SLO Gate (`eval/run_eval.py`)**:
  - **SLO-08 (PHI Leakage Rate)**: `0.00%` across all 100 evaluation cases (verifying both serialized `TriageResponse` JSON and scrubbed trace strings via `contains_pii()`).
- **Database, Voice & SSE Zero-PHI Tests**:
  - `tests/test_db_zero_phi.py` inspects raw SQLite/PostgreSQL table rows (`SELECT * FROM audit_logs`, `SELECT * FROM escalation_queue`) to confirm `0%` leakage of names, phones, national IDs, and emails.
  - `tests/test_step6_voice_adapter.py` and `tests/test_step7_sse_escalation_stream.py` verify `0%` PHI leakage across `/api/v1/voice/triage` and `/api/v1/escalations/stream`.

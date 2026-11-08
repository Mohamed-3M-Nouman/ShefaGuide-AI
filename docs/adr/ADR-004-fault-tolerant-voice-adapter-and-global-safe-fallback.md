# ADR-004: Fault-Tolerant Bi-Directional Voice Adapter & Global Safe Fallback Architecture

- **Status**: Accepted — Production Baseline
- **Date**: 2026-11-08
- **Deciders**: ShefaGuide AI Platform Reliability & Gateway Engineering Team (DEPI Capstone)
- **Target SLOs**: SLO-03 (100.00% Disclaimer Compliance), SLO-06 (100.00% Voice Timeout Graceful Fallback <= 2.5s), SLO-07 (0.00% Unhandled Exception Rate / HTTP 500s on Triage Routes)

---

## Context & Problem Statement

Many Egyptian patients—particularly elderly patients or those experiencing acute distress—prefer speaking their symptoms aloud in Egyptian Arabic rather than typing. However, integrating external Speech-to-Text (STT) and Text-to-Speech (TTS) cloud providers introduces significant reliability hazards:
1. **Network Timeouts & Provider Outages**: External STT/TTS APIs can experience high tail latency (> 5–10 seconds) or HTTP 5xx outages, stalling clinical triage when a patient needs immediate guidance.
2. **Missing Spoken Medical Disclaimers**: When triage guidance is read aloud via TTS, omitting the mandatory Arabic clinical disclaimer (`DEFAULT_DISCLAIMER_AR`) violates ethical guardrails (SLO-03).
3. **Unhandled Gateway Exceptions (HTTP 500)**: Malformed client payloads, missing API keys, database connection drops, or unexpected downstream exceptions must never surface as raw HTTP 500 stack traces to a patient seeking medical direction.

---

## Architectural Decision

We designed a **Fault-Tolerant Bi-Directional Voice & Gateway Fallback Architecture** anchored on three principles:

1. **Strict 2.5-Second Timeout & Graceful Text Degradation (`app/voice/adapter.py`)**:
   - `VoiceAdapter.transcribe_audio()` enforces a strict upper-bound timeout (`settings.VOICE_TIMEOUT_SECONDS = 2.5` seconds) via both `asyncio.wait_for` and `httpx.Timeout(2.5)`.
   - When `GROQ_API_KEY` is configured, audio bytes are sent in-memory via multipart form upload to Groq's `whisper-large-v3` endpoint (`settings.GROQ_API_URL`) with `language="ar"`.
   - If `GROQ_API_KEY` is unconfigured, `audio_bytes` is empty, or `httpx` raises `TimeoutException`, `HTTPStatusError`, or any unexpected `Exception`, `transcribe_audio()` **never raises**:
     - If `fallback_text` is provided in the request, it seamlessly returns `TranscriptionResult(success=True, text=fallback_text, fallback_to_text=True)`.
     - Otherwise, it returns `TranscriptionResult(success=False, text="", fallback_to_text=True, error_reason_ar=...)` so the client UI can immediately prompt the user to type their symptoms.

2. **Mandatory Spoken Disclaimer & In-Memory WAV Synthesis (`app/voice/adapter.py`)**:
   - `VoiceAdapter.synthesize_speech()` passes all spoken output through `ensure_spoken_disclaimer(text, include_disclaimer=True)`, guaranteeing that `DEFAULT_DISCLAIMER_AR` is appended to `spoken_text_ar` without duplication (100% SLO-03 compliance).
   - Generates a lightweight, standards-compliant 16-bit PCM mono WAV payload (`8000 Hz`) in memory (`io.BytesIO` + `wave`) within the `2.5s` timeout budget, falling back cleanly to `SynthesisResult(success=False, fallback_to_text=True, spoken_text_ar=spoken_text_ar, audio_base64=None)` if any synthesis timeout or error occurs.

3. **Zero-500 Global Safe Fallback Handlers (`app/main.py`, `app/services/triage_service.py`)**:
   - On `POST /api/v1/triage` and `POST /api/v1/voice/triage` (and root aliases `/triage`, `/voice/triage`), custom FastAPI exception handlers (`validation_exception_handler`, `http_exception_handler`, `global_exception_handler`) and endpoint `try/except` blocks catch `RequestValidationError`, HTTP 400/422 errors, STT failures without `fallback_text`, and any unexpected runtime exceptions.
   - Instead of returning HTTP 500, the gateway constructs a schema-valid **Level 3 (`UrgencyLevel.AMBIGUOUS_SEE_DOCTOR`)** `TriageResponse` (`create_fallback_triage_response` / `create_fallback_voice_triage_response`) instructing the patient in clear Arabic to consult a physician directly or type their symptoms, accompanied by an authoritative WHO fallback citation (`WHO-FALLBACK-001`) and `DEFAULT_DISCLAIMER_AR`.

---

## Technical Implementation in Repository

- **Configuration (`app/core/config.py`, `.env.example`)**:
  - Centralizes `GROQ_API_KEY`, `GROQ_STT_MODEL="whisper-large-v3"`, `GROQ_API_URL`, `VOICE_TIMEOUT_SECONDS=2.5`, and `TTS_PROVIDER="edge-or-browser-fallback"`.
- **Voice Adapter & Contracts (`app/voice/adapter.py`, `app/schemas/triage.py`)**:
  - `VoiceTranscribeRequest`, `TranscriptionResult`, `VoiceSynthesizeRequest`, `SynthesisResult`, `VoiceTriageRequest`, `VoiceTriageResponse`, and `VoiceAdapter`.
- **FastAPI Gateway Endpoints (`app/main.py`)**:
  - `POST /api/v1/voice/transcribe` (and `/voice/transcribe`)
  - `POST /api/v1/voice/synthesize` (and `/voice/synthesize`)
  - `POST /api/v1/voice/triage` (and `/voice/triage`): orchestrates Step A (STT <= 2.5s) -> Step B/C (Core Triage Pipeline with `input_mode="voice"` or Level 3 Safe Fallback + Zero-PHI Audit & SSE Broadcast) -> Step D (TTS <= 2.5s).
- **Sliding-Window Rate Limiter (`app/core/rate_limiter.py`)**:
  - Protects all triage and voice endpoints (`15 requests / 60 seconds` per client IP), returning a structured Level 3 fallback payload with `Retry-After` headers when rate limits are exceeded.

---

## Consequences

### Positive
- **Zero Single Points of Failure**: External STT, TTS, LLM, Qdrant, or PostgreSQL outages never crash the gateway or leave a patient without safe medical referral guidance.
- **Deterministic Latency Bound**: Voice operations are strictly capped at `2.5s` each, preventing hung connections.
- **100% Ethical Guardrail Enforcement**: Every text and voice response carries `DEFAULT_DISCLAIMER_AR` and passes Pydantic diagnosis/medication prohibition validators (`FORBIDDEN_DIAGNOSIS_PATTERNS`, `FORBIDDEN_MEDICATION_PATTERNS`).

### Trade-offs
- Returning HTTP `200 OK` with a Level 3 `AMBIGUOUS_SEE_DOCTOR` fallback payload on malformed triage requests prioritizes clinical client resilience (SLO-07) over strict REST 4xx/5xx error codes; clients inspect `urgency_level == 3` and `transcription.fallback_to_text` for UX banners.

---

## DEPI SLO Verification Evidence

- **Automated Evaluation (`eval/run_eval.py`)**:
  - **SLO-03 (Disclaimer & Citation Compliance)**: `100.00%`.
  - **SLO-07 (Unhandled Exception Rate)**: `0.00%`.
- **Failure-Injection & Chaos Tests (`tests/test_step6_voice_adapter.py`, `tests/test_step1_fastapi_gateway.py`)**:
  - Verified `httpx.TimeoutException`, `asyncio.TimeoutError` (> 2.5s), HTTP 500 upstream responses, missing `GROQ_API_KEY`, malformed JSON payloads, and simulated pipeline crashes all return schema-valid responses with `0` unhandled exceptions.

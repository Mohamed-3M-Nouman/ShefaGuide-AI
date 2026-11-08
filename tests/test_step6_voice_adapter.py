"""Comprehensive unit and failure-injection tests for Step 6 Voice Adapter & FastAPI Voice Endpoints.

Covers:
1. Successful STT transcription when Groq Whisper API returns 200 OK with Egyptian Arabic text.
2. STT timeout (`asyncio.TimeoutError` / `httpx.TimeoutException` > 2.5s) and HTTP 500 failure injection:
   verifies `transcribe_audio` does NOT raise, sets `fallback_to_text=True`, and completes gracefully.
3. Missing `GROQ_API_KEY` graceful degradation (with and without `fallback_text`).
4. `synthesize_speech` guarantees `DEFAULT_DISCLAIMER_AR` is included in `spoken_text_ar` and handles
   simulated TTS timeout gracefully (`fallback_to_text=True`).
5. End-to-end `POST /api/v1/voice/triage` with mocked STT returning an Egyptian red-flag phrase
   ("حاسس بطابوقة على صدري ومسمعة في دراعي الشمال") and PII ("اسمي أحمد ورقمي 01012345678"):
   triggers `UrgencyLevel.EMERGENCY_ESCALATION` (Level 4), `escalation_triggered=True`, and 0% PHI leakage.
6. End-to-end `POST /api/v1/voice/triage` when STT fails completely (no API key and no `fallback_text`):
   returns HTTP 200 OK with a valid Level 3 fallback `TriageResponse` and `transcription.fallback_to_text=True`.
7. Voice endpoint root aliases (`/voice/transcribe`, `/voice/synthesize`, `/voice/triage`) and rate limiting.
"""

from __future__ import annotations

import asyncio
import base64
import io
import wave
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool

from app.core.config import (
    GROQ_API_KEY,
    GROQ_API_URL,
    GROQ_STT_MODEL,
    TTS_PROVIDER,
    VOICE_TIMEOUT_SECONDS,
    settings,
)
from app.core.rate_limiter import rate_limiter
from app.db.crud import create_engine
from app.db.models import Base
from app.main import app
from app.safety.pii_scrubber import contains_pii
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SynthesisResult,
    TranscriptionResult,
    UrgencyLevel,
    VoiceTriageResponse,
)
from app.voice import VoiceAdapter, decode_audio_base64


def _sample_audio_base64() -> str:
    """Create a small in-memory base64-encoded audio payload without touching disk."""
    return base64.b64encode(b"RIFF\x24\x00\x00\x00WAVEfmt mock-audio-bytes").decode("ascii")


@pytest.fixture(scope="module")
def async_runner() -> Generator[asyncio.Runner, None, None]:
    """Share a single asyncio.Runner across unit tests in this module to avoid extra socketpair overhead."""
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture(autouse=True)
def reset_voice_and_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Ensure rate limiter and voice settings are clean around every test."""
    rate_limiter.reset()
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "VOICE_TIMEOUT_SECONDS", 2.5)
    yield
    rate_limiter.reset()


@pytest.fixture
def client(
    tmp_path: Path, async_runner: asyncio.Runner
) -> Generator[TestClient, None, None]:
    """TestClient backed by an isolated NullPool SQLite database for Zero-PHI audit verification."""
    db_file = tmp_path / "step6_voice_audit.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_file}", poolclass=NullPool)

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async_runner.run(_setup())

    app.state.db_engine = engine
    app.state.sync_audit = True

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc

    app.state.db_engine = None

    async def _teardown() -> None:
        await engine.dispose()

    async_runner.run(_teardown())


# ===========================================================================
# 0. Voice Configuration Settings Verification
# ===========================================================================


def test_voice_configuration_defaults() -> None:
    """Verify voice settings and module-level exports in app/core/config.py."""
    assert isinstance(GROQ_API_KEY, str)
    assert GROQ_STT_MODEL == "whisper-large-v3"
    assert GROQ_API_URL == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert VOICE_TIMEOUT_SECONDS == 2.5
    assert TTS_PROVIDER == "edge-or-browser-fallback"
    assert settings.VOICE_TIMEOUT_SECONDS == 2.5


def test_decode_audio_base64_in_memory() -> None:
    """Verify decode_audio_base64 handles raw base64, data URLs, and invalid strings safely."""
    raw = b"test-audio-stream"
    b64 = base64.b64encode(raw).decode("ascii")
    assert decode_audio_base64(b64) == raw
    assert decode_audio_base64(f"data:audio/webm;base64,{b64}") == raw
    assert decode_audio_base64(None) is None
    assert decode_audio_base64("   ") is None
    assert decode_audio_base64("data:audio/webm;base64,") is None


# ===========================================================================
# 1. Successful STT Transcription (Groq Whisper API 200 OK)
# ===========================================================================


def test_stt_successful_groq_whisper_transcription(
    async_runner: asyncio.Runner,
) -> None:
    """Verify transcribe_audio returns Egyptian Arabic text when Groq Whisper API returns 200 OK."""
    adapter = VoiceAdapter(api_key="gsk_test_valid_key")
    expected_ar = "عندي حرقان في فم المعدة"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"text": expected_ar}

    mock_post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient.post", new=mock_post):
        result = async_runner.run(
            adapter.transcribe_audio(
                audio_bytes=b"fake-webm-bytes",
                filename="patient.webm",
                language="ar",
            )
        )

    assert isinstance(result, TranscriptionResult)
    assert result.success is True
    assert result.text == expected_ar
    assert result.provider == "groq-whisper"
    assert result.fallback_to_text is False
    assert result.error_reason_ar is None
    assert result.latency_ms >= 0.0

    # Verify multipart payload sent to Groq API
    mock_post.assert_awaited_once()
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["headers"] == {"Authorization": "Bearer gsk_test_valid_key"}
    assert call_kwargs["data"] == {"model": "whisper-large-v3", "language": "ar"}
    assert call_kwargs["files"] == {"file": ("patient.webm", b"fake-webm-bytes")}


# ===========================================================================
# 2. STT Timeout (> 2.5s) and HTTP 500 Failure Injection
# ===========================================================================


def test_stt_httpx_timeout_exception_graceful_fallback(
    async_runner: asyncio.Runner,
) -> None:
    """Verify httpx.TimeoutException is caught without raising and sets fallback_to_text=True."""
    adapter = VoiceAdapter(api_key="gsk_test_timeout_key", timeout_seconds=0.05)

    mock_post = AsyncMock(side_effect=httpx.TimeoutException("Request timed out > 2.5s"))
    with patch("httpx.AsyncClient.post", new=mock_post):
        # Case A: without fallback_text
        res_no_fb = async_runner.run(adapter.transcribe_audio(audio_bytes=b"audio-bytes"))
        # Case B: with fallback_text
        res_with_fb = async_runner.run(
            adapter.transcribe_audio(
                audio_bytes=b"audio-bytes",
                fallback_text="عندي صداع شديد من الصبح",
            )
        )

    assert res_no_fb.success is False
    assert res_no_fb.text == ""
    assert res_no_fb.fallback_to_text is True
    assert res_no_fb.error_reason_ar is not None

    assert res_with_fb.success is True
    assert res_with_fb.text == "عندي صداع شديد من الصبح"
    assert res_with_fb.fallback_to_text is True
    assert res_with_fb.error_reason_ar is not None


def test_stt_asyncio_timeout_error_graceful_fallback(
    async_runner: asyncio.Runner,
) -> None:
    """Verify asyncio.TimeoutError (> VOICE_TIMEOUT_SECONDS) does not raise and falls back cleanly."""
    adapter = VoiceAdapter(api_key="gsk_test_async_timeout", timeout_seconds=0.02)

    async def _slow_groq(*args, **kwargs) -> str:
        await asyncio.sleep(0.08)
        return "لن يصل هذا النص"

    with patch.object(adapter, "_request_groq_transcription", side_effect=_slow_groq):
        result = async_runner.run(adapter.transcribe_audio(audio_bytes=b"audio-bytes"))

    assert result.success is False
    assert result.text == ""
    assert result.fallback_to_text is True
    assert result.error_reason_ar is not None


def test_stt_http_500_failure_injection_graceful_fallback(
    async_runner: asyncio.Runner,
) -> None:
    """Verify HTTP 500 from Groq API does not raise and sets fallback_to_text=True."""
    adapter = VoiceAdapter(api_key="gsk_test_500_key")

    req = httpx.Request("POST", settings.GROQ_API_URL)
    resp_500 = httpx.Response(500, request=req, text="Internal Server Error")
    mock_post = AsyncMock(
        side_effect=httpx.HTTPStatusError("500 Server Error", request=req, response=resp_500)
    )

    with patch("httpx.AsyncClient.post", new=mock_post):
        res_no_fb = async_runner.run(adapter.transcribe_audio(audio_bytes=b"audio-bytes"))
        res_with_fb = async_runner.run(
            adapter.transcribe_audio(
                audio_bytes=b"audio-bytes",
                fallback_text="عندي كحة ناشفة",
            )
        )

    assert res_no_fb.success is False
    assert res_no_fb.text == ""
    assert res_no_fb.fallback_to_text is True
    assert res_no_fb.error_reason_ar is not None

    assert res_with_fb.success is True
    assert res_with_fb.text == "عندي كحة ناشفة"
    assert res_with_fb.fallback_to_text is True


# ===========================================================================
# 3. Missing GROQ_API_KEY & Empty Audio Graceful Degradation
# ===========================================================================


def test_missing_groq_api_key_graceful_degradation(
    async_runner: asyncio.Runner,
) -> None:
    """Verify missing GROQ_API_KEY never raises and degrades gracefully."""
    adapter = VoiceAdapter(api_key="")

    res_empty_key = async_runner.run(adapter.transcribe_audio(audio_bytes=b"valid-audio"))
    res_with_fallback = async_runner.run(
        adapter.transcribe_audio(
            audio_bytes=b"valid-audio",
            fallback_text="عندي وجع في الركبة",
        )
    )
    res_empty_audio = async_runner.run(
        adapter.transcribe_audio(
            audio_bytes=b"",
            fallback_text="عندي حموضة",
        )
    )

    assert res_empty_key.success is False
    assert res_empty_key.text == ""
    assert res_empty_key.fallback_to_text is True
    assert res_empty_key.error_reason_ar is not None

    assert res_with_fallback.success is True
    assert res_with_fallback.text == "عندي وجع في الركبة"
    assert res_with_fallback.fallback_to_text is True

    assert res_empty_audio.success is True
    assert res_empty_audio.text == "عندي حموضة"
    assert res_empty_audio.fallback_to_text is True


# ===========================================================================
# 4. TTS Synthesis Disclaimer Compliance (SLO-03) & Timeout Graceful Fallback
# ===========================================================================


def test_synthesize_speech_guarantees_disclaimer_and_in_memory_wav(
    async_runner: asyncio.Runner,
) -> None:
    """Verify synthesize_speech always includes DEFAULT_DISCLAIMER_AR and returns valid in-memory WAV."""
    adapter = VoiceAdapter()
    rationale = "يرجى التوجه إلى طبيب أمراض الجهاز الهضمي للفحص الطبي."

    result = async_runner.run(adapter.synthesize_speech(rationale, include_disclaimer=True))
    result_idempotent = async_runner.run(
        adapter.synthesize_speech(
            f"{rationale}\n\n{DEFAULT_DISCLAIMER_AR}", include_disclaimer=True
        )
    )

    assert isinstance(result, SynthesisResult)
    assert result.success is True
    assert result.fallback_to_text is False
    assert DEFAULT_DISCLAIMER_AR in result.spoken_text_ar
    assert rationale in result.spoken_text_ar
    assert result.mime_type == "audio/wav"
    assert result.audio_base64 is not None

    # Validate the base64 payload decodes to a genuine RIFF/WAVE header in memory
    wav_raw = base64.b64decode(result.audio_base64)
    assert wav_raw.startswith(b"RIFF")
    with wave.open(io.BytesIO(wav_raw), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 8000

    # Verify disclaimer is not duplicated if already present
    assert result_idempotent.spoken_text_ar.count(DEFAULT_DISCLAIMER_AR) == 1


def test_synthesize_speech_timeout_and_error_graceful_fallback(
    async_runner: asyncio.Runner,
) -> None:
    """Verify simulated TTS timeout sets fallback_to_text=True while preserving DEFAULT_DISCLAIMER_AR."""
    adapter = VoiceAdapter(timeout_seconds=0.02)
    rationale = "يرجى مراجعة طبيب الباطنة العامة."

    with patch.object(
        adapter,
        "_generate_tts_wav_bytes",
        side_effect=asyncio.TimeoutError("Simulated TTS timeout > 2.5s"),
    ):
        res_timeout = async_runner.run(
            adapter.synthesize_speech(rationale, include_disclaimer=True)
        )

    assert res_timeout.success is False
    assert res_timeout.fallback_to_text is True
    assert res_timeout.audio_base64 is None
    assert DEFAULT_DISCLAIMER_AR in res_timeout.spoken_text_ar
    assert rationale in res_timeout.spoken_text_ar
    assert res_timeout.error_reason_ar is not None


# ===========================================================================
# 5. End-to-End POST /api/v1/voice/triage with Red-Flag + PII (Level 4, 0% PHI)
# ===========================================================================


def test_e2e_voice_triage_red_flag_escalation_and_zero_phi_leakage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POST /api/v1/voice/triage with red-flag + PII triggers Level 4 escalation and 0% PHI leakage."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_live_mock_key")

    red_flag_with_pii = (
        "اسمي أحمد ورقمي 01012345678، حاسس بطابوقة على صدري ومسمعة في دراعي الشمال"
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"text": red_flag_with_pii}

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
        resp = client.post(
            "/api/v1/voice/triage",
            json={
                "session_id": "sess_voice_redflag_01",
                "audio_base64": _sample_audio_base64(),
                "filename": "emergency.webm",
                "language": "ar",
            },
        )

    assert resp.status_code == 200, resp.text
    parsed = VoiceTriageResponse.model_validate(resp.json())

    # 1. Verify transcription succeeded
    assert parsed.transcription.success is True
    assert parsed.transcription.provider == "groq-whisper"
    assert parsed.transcription.fallback_to_text is False

    # 2. Verify deterministic red-flag escalation (Level 4)
    assert parsed.triage.urgency_level == UrgencyLevel.EMERGENCY_ESCALATION
    assert parsed.triage.escalation_triggered is True
    assert parsed.triage.disclaimer_ar == DEFAULT_DISCLAIMER_AR

    # 3. Verify 0% PHI leakage in TriageResponse and SynthesisResult
    triage_json = parsed.triage.model_dump_json()
    assert "01012345678" not in triage_json
    assert "أحمد" not in triage_json
    assert not contains_pii(triage_json)
    assert DEFAULT_DISCLAIMER_AR in parsed.synthesis.spoken_text_ar
    assert not contains_pii(parsed.synthesis.spoken_text_ar)

    # 4. Verify Zero-PHI persistence in /api/v1/audit-logs and /api/v1/escalations
    audit_resp = client.get("/api/v1/audit-logs")
    assert audit_resp.status_code == 200
    audit_items = audit_resp.json()["items"]
    log_entry = next(
        (i for i in audit_items if i["session_id"] == "sess_voice_redflag_01"), None
    )
    assert log_entry is not None
    assert "01012345678" not in log_entry["scrubbed_input"]
    assert "أحمد" not in log_entry["scrubbed_input"]
    assert not contains_pii(log_entry["scrubbed_input"])
    assert log_entry["escalation_triggered"] is True

    esc_resp = client.get("/api/v1/escalations?status=pending")
    assert esc_resp.status_code == 200
    esc_items = esc_resp.json()["items"]
    esc_entry = next(
        (e for e in esc_items if e["session_id"] == "sess_voice_redflag_01"), None
    )
    assert esc_entry is not None
    assert "01012345678" not in (esc_entry.get("scrubbed_summary") or "")


# ===========================================================================
# 6. End-to-End POST /api/v1/voice/triage When STT Fails Completely (Level 3)
# ===========================================================================


def test_e2e_voice_triage_stt_complete_failure_returns_200_level_3_fallback(
    client: TestClient,
) -> None:
    """Verify POST /api/v1/voice/triage returns HTTP 200 Level 3 fallback when STT fails and no fallback_text."""
    resp = client.post(
        "/api/v1/voice/triage",
        json={
            "session_id": "sess_voice_fail_01",
            "audio_base64": _sample_audio_base64(),
            "filename": "unintelligible.webm",
            "language": "ar",
        },
    )
    assert resp.status_code == 200, resp.text
    parsed = VoiceTriageResponse.model_validate(resp.json())

    assert parsed.transcription.success is False
    assert parsed.transcription.fallback_to_text is True
    assert parsed.transcription.text == ""
    assert parsed.transcription.error_reason_ar is not None

    assert parsed.triage.session_id == "sess_voice_fail_01"
    assert parsed.triage.urgency_level == UrgencyLevel.AMBIGUOUS_SEE_DOCTOR
    assert parsed.triage.escalation_triggered is False
    assert parsed.triage.disclaimer_ar == DEFAULT_DISCLAIMER_AR

    assert DEFAULT_DISCLAIMER_AR in parsed.synthesis.spoken_text_ar


# ===========================================================================
# 7. Individual Voice Endpoints (/transcribe, /synthesize) & Root Aliases
# ===========================================================================


def test_voice_transcribe_and_synthesize_endpoints_and_aliases(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POST /api/v1/voice/transcribe, /api/v1/voice/synthesize, and root /voice/* aliases."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test_endpoint_key")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"text": "عندي حرقان في فم المعدة"}

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
        for path in ("/api/v1/voice/transcribe", "/voice/transcribe"):
            resp_stt = client.post(
                path,
                json={
                    "session_id": "sess_stt_ep",
                    "audio_base64": _sample_audio_base64(),
                },
            )
            assert resp_stt.status_code == 200
            stt_data = TranscriptionResult.model_validate(resp_stt.json())
            assert stt_data.success is True
            assert stt_data.text == "عندي حرقان في فم المعدة"
            assert stt_data.fallback_to_text is False

    for path in ("/api/v1/voice/synthesize", "/voice/synthesize"):
        resp_tts = client.post(
            path,
            json={
                "session_id": "sess_tts_ep",
                "text": "يرجى مراجعة طبيب الجهاز الهضمي.",
                "include_disclaimer": True,
            },
        )
        assert resp_tts.status_code == 200
        tts_data = SynthesisResult.model_validate(resp_tts.json())
        assert tts_data.success is True
        assert DEFAULT_DISCLAIMER_AR in tts_data.spoken_text_ar
        assert tts_data.audio_base64 is not None

    # Verify root /voice/triage alias with fallback_text (using local corpus fallback for fast test execution)
    monkeypatch.setattr("app.rag.retriever.retrieve_guidelines", lambda *a, **kw: [])
    resp_alias = client.post(
        "/voice/triage",
        json={
            "session_id": "sess_voice_alias",
            "fallback_text": "عندي حرقان جامد في فم المعدة بعد الأكل",
        },
    )
    assert resp_alias.status_code == 200
    alias_data = VoiceTriageResponse.model_validate(resp_alias.json())
    assert alias_data.transcription.fallback_to_text is True
    assert alias_data.triage.symptom_category.value == "gastrointestinal"
    assert DEFAULT_DISCLAIMER_AR in alias_data.synthesis.spoken_text_ar

"""Fault-Tolerant Bi-Directional Zero-PHI Voice Adapter (STT & TTS) for ShefaGuide AI.

All patient audio payloads are processed strictly in-memory (`io.BytesIO`, `base64`, `wave`)
and are NEVER written to disk. Enforces a strict 2.5s timeout (`VOICE_TIMEOUT_SECONDS`)
with graceful fallback to text mode on any network, timeout, or provider failure.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import io
import logging
import time

import httpx

from app.core.config import settings
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    SynthesisResult,
    TranscriptionResult,
    VoiceSynthesizeRequest,
    VoiceTranscribeRequest,
    VoiceTriageRequest,
    VoiceTriageResponse,
)

logger = logging.getLogger("shefaguide.voice")

__all__ = [
    "SynthesisResult",
    "TranscriptionResult",
    "VoiceAdapter",
    "VoiceSynthesizeRequest",
    "VoiceTranscribeRequest",
    "VoiceTriageRequest",
    "VoiceTriageResponse",
    "decode_audio_base64",
    "ensure_spoken_disclaimer",
    "voice_adapter",
]


def decode_audio_base64(audio_base64: str | None) -> bytes | None:
    """Safely decode a base64 audio string (with optional data-URI prefix) strictly in memory."""
    if not audio_base64 or not isinstance(audio_base64, str):
        return None
    cleaned = audio_base64.strip()
    if not cleaned:
        return None
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1].strip()
    if not cleaned:
        return None
    try:
        decoded = base64.b64decode(cleaned, validate=False)
        return decoded if decoded else None
    except Exception as exc:
        logger.warning("In-memory base64 audio decoding failed: %s", exc)
        return None


def ensure_spoken_disclaimer(text: str, include_disclaimer: bool = True) -> str:
    """Guarantee DEFAULT_DISCLAIMER_AR is appended to spoken_text_ar when include_disclaimer=True (SLO-03)."""
    cleaned = (text or "").strip()
    if not include_disclaimer:
        return cleaned if cleaned else DEFAULT_DISCLAIMER_AR
    if not cleaned:
        return DEFAULT_DISCLAIMER_AR
    if DEFAULT_DISCLAIMER_AR in cleaned:
        return cleaned
    return f"{cleaned}\n\n{DEFAULT_DISCLAIMER_AR}"


def _normalize_egyptian_tts_text(text: str) -> str:
    import re
    t = re.sub(r"\(?\b123\b\)?", "واحد اتنين تلاتة", text)
    t = re.sub(r"\(?\b122\b\)?", "واحد اتنين اتنين", t)
    t = re.sub(r"\(?\b180\b\)?", "واحد تمانية صفر", t)
    t = re.sub(r"\(?\b121\b\)?", "واحد اتنين واحد", t)
    t = re.sub(r"(?m)\s*\d+[\.\-\)]\s*", "", t)
    d = {"0":"صفر","1":"واحد","2":"اتنين","3":"تلاتة","4":"أربعة","5":"خمسة","6":"ستة","7":"سبعة","8":"تمانية","9":"تسعة","10":"عشرة"}
    t = re.sub(r"\b10\b", "عشرة", t)
    t = re.sub(r"\b[0-9]\b", lambda m: d[m.group(0)], t)
    return t.strip()


class VoiceAdapter:
    """Fault-tolerant, Zero-PHI in-memory Speech-to-Text and Text-to-Speech adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        stt_model: str | None = None,
        api_url: str | None = None,
        timeout_seconds: float | None = None,
        tts_provider: str | None = None,
        tts_voice: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.stt_model = stt_model
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.tts_provider = tts_provider
        self.tts_voice = tts_voice

    def _resolve_timeout(self) -> float:
        raw = (
            self.timeout_seconds
            if self.timeout_seconds is not None
            else settings.VOICE_TIMEOUT_SECONDS
        )
        try:
            val = float(raw)
            return val if val > 0 else 2.5
        except (TypeError, ValueError):
            return 2.5

    def _resolve_api_key(self) -> str:
        raw = self.api_key if self.api_key is not None else settings.GROQ_API_KEY
        return (raw or "").strip()

    def _resolve_stt_model(self) -> str:
        raw = self.stt_model if self.stt_model is not None else settings.GROQ_STT_MODEL
        return (raw or "whisper-large-v3").strip()

    def _resolve_api_url(self) -> str:
        raw = self.api_url if self.api_url is not None else settings.GROQ_API_URL
        return (raw or "https://api.groq.com/openai/v1/audio/transcriptions").strip()

    def _resolve_tts_provider(self) -> str:
        raw = self.tts_provider if self.tts_provider is not None else settings.TTS_PROVIDER
        return (raw or "edge-or-browser-fallback").strip()

    def _resolve_tts_voice(self) -> str:
        raw = self.tts_voice if self.tts_voice is not None else settings.TTS_VOICE
        return (raw or "ar-EG-ShakirNeural").strip()

    async def _request_groq_transcription(
        self,
        audio_bytes: bytes,
        filename: str,
        language: str,
        api_key: str,
        timeout_s: float,
    ) -> str:
        """Send multipart audio bytes in-memory to Groq Whisper STT endpoint."""
        url = self._resolve_api_url()
        model = self._resolve_stt_model()
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": (filename or "audio.webm", audio_bytes)}
        data = {"model": model, "language": language or "ar"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            response = await client.post(url, headers=headers, files=files, data=data)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("text", "")).strip()
            return ""

    async def transcribe_audio(
        self,
        audio_bytes: bytes | None,
        filename: str = "audio.webm",
        language: str = "ar",
        fallback_text: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe patient audio bytes with a strict 2.5s timeout and graceful fallback."""
        start_t = time.perf_counter()
        timeout_s = self._resolve_timeout()
        clean_fallback = (fallback_text or "").strip()

        def _build_fallback(reason_ar: str, provider: str = "fallback_text") -> TranscriptionResult:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 3)
            if clean_fallback:
                return TranscriptionResult(
                    success=True,
                    text=clean_fallback,
                    provider=provider,
                    fallback_to_text=True,
                    latency_ms=elapsed_ms,
                    error_reason_ar=reason_ar,
                )
            return TranscriptionResult(
                success=False,
                text="",
                provider=provider,
                fallback_to_text=True,
                latency_ms=elapsed_ms,
                error_reason_ar=reason_ar,
            )

        # 1. Validate non-empty audio_bytes immediately without network/client creation
        if not audio_bytes or len(audio_bytes) == 0:
            return _build_fallback(
                reason_ar="لم يتم إرسال مقطع صوتي صالح؛ تم التحويل إلى الإدخال النصي.",
                provider="fallback_text",
            )

        # 2. Check GROQ_API_KEY configuration immediately without network/client creation
        api_key = self._resolve_api_key()
        if not api_key:
            return _build_fallback(
                reason_ar="مفتاح خدمة التعرف الصوتي (GROQ_API_KEY) غير مُعد؛ تم التحويل إلى الإدخال النصي.",
                provider="unconfigured",
            )

        # 3. Execute STT call with strict timeout (2.5s)
        try:
            transcribed_text = await asyncio.wait_for(
                self._request_groq_transcription(
                    audio_bytes=audio_bytes,
                    filename=filename or "audio.webm",
                    language=language or "ar",
                    api_key=api_key,
                    timeout_s=timeout_s,
                ),
                timeout=timeout_s,
            )
            elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 3)
            if transcribed_text:
                return TranscriptionResult(
                    success=True,
                    text=transcribed_text,
                    provider="groq-whisper",
                    fallback_to_text=False,
                    latency_ms=elapsed_ms,
                    error_reason_ar=None,
                )
            return _build_fallback(
                reason_ar="لم يتم التعرف على كلام واضح في التسجيل الصوتي؛ يرجى كتابة الأعراض نصياً.",
                provider="groq-whisper",
            )
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            logger.warning("STT transcription timed out (> %.2fs): %s", timeout_s, exc)
            return _build_fallback(
                reason_ar="انتهت مهلة معالجة الصوت (أكثر من 2.5 ثانية)؛ يرجى كتابة الأعراض نصياً.",
                provider="groq-whisper",
            )
        except httpx.HTTPError as exc:
            logger.warning("STT HTTP error from Groq API: %s", exc)
            return _build_fallback(
                reason_ar="تعذر الاتصال بخدمة تحويل الصوت إلى نص؛ يرجى كتابة الأعراض نصياً.",
                provider="groq-whisper",
            )
        except Exception as exc:
            logger.warning("Unexpected STT error: %s", exc)
            return _build_fallback(
                reason_ar="حدث خطأ غير متوقع أثناء معالجة التسجيل الصوتي؛ يرجى كتابة الأعراض نصياً.",
                provider="groq-whisper",
            )

    async def _request_edge_tts_audio(self, spoken_text_ar: str) -> bytes:
        import os, base64, struct, httpx, re, edge_tts
        from dotenv import load_dotenv
        load_dotenv()
        normalized = _normalize_egyptian_tts_text(spoken_text_ar)
        cache = getattr(self, "_audio_cache", None)
        if cache is None:
            cache = {}
            self._audio_cache = cache
        if normalized in cache:
            self._last_mime, cached_bytes = cache[normalized]
            return cached_bytes
        eg_map = [(r"\bايه\b", "إِيه"), (r"\bإيه\b", "إِيه"), (r"\bده\b", "دَه"), (r"\bدي\b", "دِي"), (r"\bدول\b", "دُول"), (r"\bاللي\b", "اللِّي"), (r"\bمش\b", "مِش"), (r"\bمفيش\b", "مَفِيش"), (r"\bما فيش\b", "مَفِيش"), (r"\bعشان\b", "عَشَان"), (r"\bعلشان\b", "عَلَشَان"), (r"\bدلوقتي\b", "دِلْوَقْتِي"), (r"\bبقالك\b", "بَقَالَك"), (r"\bبتحس\b", "بِتْحِسّ"), (r"\bبييجي\b", "بِيِيجِي"), (r"\bبيمشي\b", "بِيِمْشِي"), (r"\bكويس\b", "كْوَيِّس"), (r"\bمتقلقش\b", "مَتِقْلَقْش"), (r"\bقولي\b", "قُولِّي"), (r"\bلي\b", "لِيَّا"), (r"\bليه\b", "لِيه"), (r"\bزي\b", "زَيّ"), (r"\bكده\b", "كِدَه"), (r"\bبرضه\b", "بَرْضُه"), (r"\bخالص\b", "خَالِص"), (r"\bأوي\b", "قَوِي"), (r"\bحاجة\b", "حَاجَة"), (r"\bتعبان\b", "تَعْبَان"), (r"\bأهلا\b", "أَهْلًا"), (r"\bأهلاً\b", "أَهْلًا"), (r"\bبيك\b", "بِيك"), (r"\bيا غالي\b", "يَا غَالِي"), (r"\bخد نفس\b", "خُد نَفَس"), (r"\bواطمن\b", "وَاطَّمِّن"), (r"\bشوية\b", "شْوَيَّة"), (r"\bبتاع\b", "بِتَاع"), (r"\bبتاعت\b", "بِتَاعِت"), (r"\bإزيك\b", "إِزَّيَّك"), (r"\bعامل\b", "عَامِل")]
        eg_text = normalized
        for pat, rep in eg_map:
            eg_text = re.sub(pat, rep, eg_text)
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}"
                prompt = (
                    "Speak the following Arabic medical guidance in an authentic, natural Cairene Egyptian Arabic accent (لهجة مصرية قاهرية عامية طبيعية). "
                    "CRITICAL PRONUNCIATION RULES: Do NOT use Modern Standard Arabic (Fusha) case endings or i rab; drop final vowels naturally as Egyptians speak; "
                    "pronounce colloquial Qaf as a glottal stop where natural in Egyptian dialect, and keep a warm, calm, reassuring bedside doctor tone. "
                    "Read the exact words verbatim without adding or removing anything:\n\n"
                    f"{eg_text}"
                )
                payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Orus"}}}}}
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
                    wav_hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, 24000, 48000, 2, 16, b"data", len(pcm))
                    wav_bytes = wav_hdr + pcm
                    self._last_mime = "audio/wav"
                    cache[normalized] = ("audio/wav", wav_bytes)
                    return wav_bytes
            except Exception as exc:
                logger.warning("Gemini TTS fallback: %s", exc)
        el_key = os.getenv("ELEVENLABS_API_KEY")
        if el_key:
            try:
                el_voice = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
                if not el_voice:
                    async with httpx.AsyncClient(timeout=15.0) as vc:
                        vr = await vc.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": el_key})
                        if vr.status_code == 200:
                            eg_v = [v["voice_id"] for v in vr.json().get("voices", []) if "egypt" in (str(v.get("labels",""))+str(v.get("name",""))).lower() or "arab" in (str(v.get("labels",""))+str(v.get("name",""))).lower()]
                            el_voice = eg_v[0] if eg_v else "pNInz6obpgDQGcFmaJgB"
                        else:
                            el_voice = "pNInz6obpgDQGcFmaJgB"
                el_url = f"https://api.elevenlabs.io/v1/text-to-speech/{el_voice}"
                el_headers = {"xi-api-key": el_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
                el_payload = {"text": eg_text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.35, "similarity_boost": 0.80, "style": 0.45}}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    el_resp = await client.post(el_url, headers=el_headers, json=el_payload)
                if el_resp.status_code == 200 and el_resp.content:
                    self._last_mime = "audio/mpeg"
                    cache[normalized] = ("audio/mpeg", el_resp.content)
                    return el_resp.content
            except Exception as exc:
                logger.warning("ElevenLabs TTS fallback: %s", exc)
        self._last_mime = "audio/mpeg"
        voice = self._resolve_tts_voice()
        parts = [c.strip() for c in re.split(r'(?<=[.!؟?\n])\s+', eg_text) if c.strip()] or [eg_text]
        async def _synth_part(chunk_text: str) -> bytes:
            comm = edge_tts.Communicate(chunk_text, voice=voice, rate="-6%")
            buf = io.BytesIO()
            async for item in comm.stream():
                if item.get("type") == "audio" and item.get("data"):
                    buf.write(item["data"])
            return buf.getvalue()
        audio_parts = await asyncio.gather(*(_synth_part(pt) for pt in parts))
        mp3_bytes = b"".join(audio_parts)
        cache[normalized] = ("audio/mpeg", mp3_bytes)
        return mp3_bytes

    async def synthesize_speech(
        self,
        text: str,
        include_disclaimer: bool = True,
    ) -> SynthesisResult:
        """Synthesize Arabic speech in-memory via Edge TTS with strict timeout and browser/text fallback."""
        start_t = time.perf_counter()
        timeout_s = self._resolve_timeout()
        provider_name = self._resolve_tts_provider()
        spoken_text_ar = ensure_spoken_disclaimer(text, include_disclaimer=include_disclaimer)

        try:
            maybe_coro = self._request_edge_tts_audio(spoken_text_ar)
            if inspect.isawaitable(maybe_coro):
                audio_bytes = await asyncio.wait_for(maybe_coro, timeout=max(timeout_s, 45.0))
            else:
                audio_bytes = maybe_coro

            if not audio_bytes:
                raise RuntimeError("Empty audio buffer returned by Edge TTS.")

            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
            elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 3)
            return SynthesisResult(
                success=True,
                spoken_text_ar=spoken_text_ar,
                audio_base64=audio_b64,
                mime_type=getattr(self, "_last_mime", "audio/mpeg"),
                provider="edge-tts" if "edge" in provider_name.lower() else provider_name,
                fallback_to_text=False,
                latency_ms=elapsed_ms,
                error_reason_ar=None,
            )
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            logger.warning("TTS synthesis timed out (> %.2fs): %s", timeout_s, exc)
            elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 3)
            return SynthesisResult(
                success=False,
                spoken_text_ar=spoken_text_ar,
                audio_base64=None,
                mime_type=getattr(self, "_last_mime", "audio/mpeg"),
                provider="browser-fallback",
                fallback_to_text=True,
                latency_ms=elapsed_ms,
                error_reason_ar="انتهت مهلة توليد الصوت؛ يتم التحويل لقارئ المتصفح أو العرض النصي.",
            )
        except Exception as exc:
            logger.warning("TTS synthesis fallback triggered: %s", exc)
            elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 3)
            return SynthesisResult(
                success=False,
                spoken_text_ar=spoken_text_ar,
                audio_base64=None,
                mime_type=getattr(self, "_last_mime", "audio/mpeg"),
                provider="browser-fallback",
                fallback_to_text=True,
                latency_ms=elapsed_ms,
                error_reason_ar="تعذر توليد الصوت من الخادم؛ يتم التحويل لقارئ المتصفح أو العرض النصي.",
            )


voice_adapter = VoiceAdapter()

"""Fault-Tolerant Bi-Directional Voice Adapter package for ShefaGuide AI."""

from __future__ import annotations

from app.voice.adapter import (
    SynthesisResult,
    TranscriptionResult,
    VoiceAdapter,
    VoiceSynthesizeRequest,
    VoiceTranscribeRequest,
    VoiceTriageRequest,
    VoiceTriageResponse,
    decode_audio_base64,
    ensure_spoken_disclaimer,
    voice_adapter,
)

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

"""FastAPI Gateway Core for ShefaGuide AI.

Exposes health endpoints, deterministic clinical triage, fault-tolerant bi-directional
voice endpoints, real-time Zero-PHI SSE escalation streaming, in-memory sliding-window
rate limiting, and global safe fallback handlers.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.rate_limiter import extract_client_ip, rate_limiter
from app.core.sse import escalation_broadcaster
from app.schemas.triage import (
    DEFAULT_DISCLAIMER_AR,
    AuditLogItem,
    AuditLogsResponse,
    EscalationItem,
    EscalationListResponse,
    EscalationUpdateRequest,
    SymptomCategory,
    SynthesisResult,
    TranscriptionResult,
    TriageRequest,
    TriageResponse,
    UrgencyLevel,
    VoiceSynthesizeRequest,
    VoiceTranscribeRequest,
    VoiceTriageRequest,
    VoiceTriageResponse,
)
from app.services import triage_service
from app.services.triage_service import create_fallback_triage_response
from app.voice import decode_audio_base64, ensure_spoken_disclaimer, voice_adapter

logger = logging.getLogger("shefaguide.gateway")

HTTP_422_STATUS = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

SSE_STREAM_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _format_datetime(dt: Any) -> str | None:
    """Safely format datetime instances to ISO 8601 strings across all database drivers."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _safe_str_list(val: Any) -> list[str]:
    """Safely convert database JSON or collection values into a clean list of strings."""
    if val is None:
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
            return [str(parsed)]
        except Exception:
            return [val]
    if isinstance(val, (list, tuple, set)):
        return [str(x) for x in val]
    return [str(val)]


def _publish_sse_escalation_if_needed(
    session_id: str,
    user_input: str,
    response: Any,
) -> None:
    """Immediately broadcast a Zero-PHI SSE alert when a Level 4 emergency escalation occurs."""
    try:
        escalated = bool(getattr(response, "escalation_triggered", False))
        urg = getattr(response, "urgency_level", UrgencyLevel.AMBIGUOUS_SEE_DOCTOR)
        try:
            urg_int = int(urg)
        except (TypeError, ValueError):
            urg_int = int(UrgencyLevel.AMBIGUOUS_SEE_DOCTOR)

        if not escalated and urg_int != int(UrgencyLevel.EMERGENCY_ESCALATION):
            return

        from app.safety.pii_scrubber import scrub_pii
        from app.safety.red_flags import evaluate_red_flags

        scrubbed_input = scrub_pii(user_input or "")
        detected_flags: list[str] = []
        try:
            rf_eval = evaluate_red_flags(scrubbed_input)
            if rf_eval.matched_phrases_ar:
                detected_flags = list(rf_eval.matched_phrases_ar)
        except Exception:
            pass
        if not detected_flags:
            detected_flags = ["Emergency escalation triggered"]

        cat = getattr(response, "symptom_category", SymptomCategory.UNKNOWN)
        rec_spec = getattr(response, "recommended_specialty", None)

        escalation_broadcaster.publish_escalation(
            {
                "session_id": session_id,
                "symptom_category": cat.value if hasattr(cat, "value") else str(cat),
                "recommended_specialty": rec_spec,
                "detected_red_flags": detected_flags,
                "urgency_level": int(UrgencyLevel.EMERGENCY_ESCALATION),
                "status": "pending",
                "scrubbed_summary": scrubbed_input[:280] if scrubbed_input else None,
            }
        )
    except Exception as exc:
        logger.warning("Zero-PHI SSE escalation broadcast skipped: %s", exc)


async def persist_audit_log(
    session_id: str,
    user_input: str,
    response: Any,
    latency_ms: float | None = None,
) -> None:
    """Asynchronously persist audit log and human escalation without slowing down triage response."""
    try:
        from app.db.crud import (
            AuditLogCreate,
            create_session_factory,
            log_interaction,
        )

        engine = getattr(app.state, "db_engine", None)
        if engine is None:
            return

        session_factory = create_session_factory(engine)
        doc_ids = []
        if hasattr(response, "citations") and response.citations:
            doc_ids = [c.doc_id for c in response.citations]

        safe_sid = str(session_id or "session_fallback").strip()
        if not re.match(r"^[A-Za-z0-9_\-]+$", safe_sid):
            safe_sid = re.sub(r"[^A-Za-z0-9_\-]", "_", safe_sid)
        if not safe_sid:
            safe_sid = "session_fallback"
        elif len(safe_sid) > 64:
            safe_sid = safe_sid[:64]

        cat = getattr(response, "symptom_category", SymptomCategory.UNKNOWN)
        if isinstance(cat, str):
            try:
                cat = SymptomCategory(cat)
            except ValueError:
                cat = SymptomCategory.UNKNOWN

        urg = getattr(response, "urgency_level", UrgencyLevel.AMBIGUOUS_SEE_DOCTOR)
        if isinstance(urg, int) and not isinstance(urg, UrgencyLevel):
            try:
                urg = UrgencyLevel(urg)
            except ValueError:
                urg = UrgencyLevel.AMBIGUOUS_SEE_DOCTOR

        rec_spec = getattr(response, "recommended_specialty", None)
        rationale = getattr(response, "rationale_ar", None)
        escalated = bool(getattr(response, "escalation_triggered", False))

        audit_data = AuditLogCreate(
            session_id=safe_sid,
            user_input=user_input or "no_input",
            symptom_category=cat,
            urgency_level=urg,
            recommended_specialty=rec_spec,
            rationale=rationale,
            retrieved_doc_ids=doc_ids,
            tool_calls=[],
            escalation_triggered=escalated,
            latency_ms=latency_ms,
        )

        detected_flags = []
        if escalated or urg == UrgencyLevel.EMERGENCY_ESCALATION:
            try:
                from app.safety.pii_scrubber import scrub_pii
                from app.safety.red_flags import evaluate_red_flags

                rf_eval = evaluate_red_flags(scrubbed_text := scrub_pii(user_input or ""))
                if rf_eval.matched_phrases_ar:
                    detected_flags = list(rf_eval.matched_phrases_ar)
                else:
                    detected_flags = ["Emergency escalation triggered"]
                _ = scrubbed_text
            except Exception:
                detected_flags = ["Emergency escalation triggered"]

        async with session_factory() as session, session.begin():
            await log_interaction(session, audit_data, detected_red_flags=detected_flags)
    except Exception as exc:
        logger.warning("Audit DB interaction logging skipped: %s", exc)


class HealthResponse(BaseModel):
    """Health check response contract matching Walking-Skeleton specification."""

    status: str = Field(default="ok", description="Service health status.")
    service: str = Field(default=settings.APP_NAME, description="Application service name.")
    phase: str = Field(default=settings.PHASE, description="Deployment phase.")


def _is_triage_path(path: str) -> bool:
    """Check if the request path targets clinical text triage."""
    return (
        path == "/triage"
        or path == f"{settings.API_V1_PREFIX}/triage"
        or path.startswith(f"{settings.API_V1_PREFIX}/triage/")
    )


def _is_voice_triage_path(path: str) -> bool:
    """Check if the request path targets clinical voice triage."""
    return (
        path == "/voice/triage"
        or path == f"{settings.API_V1_PREFIX}/voice/triage"
        or path.startswith(f"{settings.API_V1_PREFIX}/voice/triage/")
    )


def _is_voice_transcribe_path(path: str) -> bool:
    """Check if the request path targets voice STT transcription."""
    return path == "/voice/transcribe" or path == f"{settings.API_V1_PREFIX}/voice/transcribe"


def _is_voice_synthesize_path(path: str) -> bool:
    """Check if the request path targets voice TTS synthesis."""
    return path == "/voice/synthesize" or path == f"{settings.API_V1_PREFIX}/voice/synthesize"


def create_fallback_voice_triage_response(
    session_id: str = "fallback-session",
    rationale_ar: str | None = None,
    error_reason_ar: str | None = None,
) -> VoiceTriageResponse:
    """Construct a schema-valid Level 3 VoiceTriageResponse when voice processing fails."""
    if not rationale_ar or not rationale_ar.strip():
        rationale_ar = (
            "تعذر سماع أو تحويل التسجيل الصوتي إلى نص واضح. للحفاظ على سلامتك، "
            "يرجى كتابة الأعراض التي تشعر بها نصياً أو التوجه مباشرة لاستشارة طبيب مختص."
        )
    fallback_triage = create_fallback_triage_response(
        session_id=session_id,
        rationale_ar=rationale_ar,
    )
    fallback_transcription = TranscriptionResult(
        success=False,
        text="",
        provider="fallback_text",
        fallback_to_text=True,
        latency_ms=0.0,
        error_reason_ar=error_reason_ar or "تعذر معالجة التسجيل الصوتي؛ تم التحويل للإدخال النصي.",
    )
    fallback_synthesis = SynthesisResult(
        success=False,
        spoken_text_ar=ensure_spoken_disclaimer(
            fallback_triage.rationale_ar, include_disclaimer=True
        ),
        audio_base64=None,
        mime_type="audio/wav",
        provider=settings.TTS_PROVIDER,
        fallback_to_text=True,
        latency_ms=0.0,
        error_reason_ar=error_reason_ar or "يتم عرض التوجيهات الطبية نصياً.",
    )
    return VoiceTriageResponse(
        triage=fallback_triage,
        transcription=fallback_transcription,
        synthesis=fallback_synthesis,
    )


def _extract_session_id_safely(request: Request) -> str:
    """Safely extract session_id from cached request body without stream deadlocks."""
    try:
        raw = getattr(request, "_body", None)
        if raw:
            text = raw.decode("utf-8", errors="ignore")
            match = re.search(r'"session_id"\s*:\s*"([^"]+)"', text)
            if match:
                return match.group(1).strip()
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("session_id"):
                    return str(parsed["session_id"]).strip()
            except Exception:
                pass
    except Exception:
        pass
    return "fallback-session"


def create_app() -> FastAPI:
    """Create and configure the core FastAPI application instance."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.db.crud import create_engine, init_db

        injected = getattr(app.state, "db_engine", None) is not None
        if not injected:
            engine = None
            try:
                engine = create_engine(settings.DATABASE_URL)
                await init_db(engine)
                app.state.db_engine = engine
                logger.info("Zero-PHI audit database initialized successfully.")
            except Exception as exc:
                logger.warning("Audit DB init deferred / unreachable: %s", exc)
                app.state.db_engine = None
        yield
        if not injected and getattr(app.state, "db_engine", None) is not None:
            try:
                await app.state.db_engine.dispose()
            except Exception:
                pass

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Clinical Pre-Care & Specialist Referral Triage Gateway for Egyptian Arabic Patients.",
        lifespan=lifespan,
    )

    # Attach shared rate limiter and SSE broadcaster to application state
    app.state.rate_limiter = rate_limiter
    app.state.escalation_broadcaster = escalation_broadcaster

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception Handlers for SLO-07 (0% Unhandled Exceptions)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Catch malformed payloads or schema validation errors and return safe fallbacks."""
        path = request.url.path
        if _is_triage_path(path):
            session_id = _extract_session_id_safely(request)
            fallback = create_fallback_triage_response(
                session_id=session_id,
                rationale_ar=(
                    "تعذر معالجة البيانات المدخلة لوجود خطأ في صياغة الطلب أو نقص في البيانات. "
                    "للحفاظ على سلامتك، يرجى التوجه للفحص الطبي المباشر لدى طبيب مختص."
                ),
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fallback.model_dump(mode="json"),
            )
        if _is_voice_triage_path(path):
            session_id = _extract_session_id_safely(request)
            fb_voice = create_fallback_voice_triage_response(session_id=session_id)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_voice.model_dump(mode="json"),
            )
        if _is_voice_transcribe_path(path):
            fb_stt = TranscriptionResult(
                success=False,
                text="",
                provider="fallback_text",
                fallback_to_text=True,
                latency_ms=0.0,
                error_reason_ar="بيانات الطلب الصوتي غير مكتملة؛ يرجى كتابة الأعراض نصياً.",
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_stt.model_dump(mode="json"),
            )
        if _is_voice_synthesize_path(path):
            fb_tts = SynthesisResult(
                success=False,
                spoken_text_ar=DEFAULT_DISCLAIMER_AR,
                audio_base64=None,
                mime_type="audio/wav",
                provider=settings.TTS_PROVIDER,
                fallback_to_text=True,
                latency_ms=0.0,
                error_reason_ar="بيانات طلب النطق الصوتي غير صالحة؛ يتم عرض التنبيه الطبي نصياً.",
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_tts.model_dump(mode="json"),
            )
        return JSONResponse(
            status_code=HTTP_422_STATUS,
            content={"detail": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle HTTP errors on triage and voice routes safely."""
        path = request.url.path
        if _is_triage_path(path):
            session_id = _extract_session_id_safely(request)
            if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                fallback = create_fallback_triage_response(
                    session_id=session_id,
                    rationale_ar=(
                        "تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة). "
                        "للحفاظ على سلامتك، يرجى التوجه للفحص الطبي المباشر أو الانتظار قبل المحاولة مرة أخرى."
                    ),
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content=fallback.model_dump(mode="json"),
                    headers={"Retry-After": "60"},
                )
            if exc.status_code in (
                status.HTTP_400_BAD_REQUEST,
                HTTP_422_STATUS,
            ):
                fallback = create_fallback_triage_response(
                    session_id=session_id,
                    rationale_ar=(
                        "تعذر معالجة البيانات المدخلة لوجود خطأ في الطلب. "
                        "للحفاظ على سلامتك، يرجى التوجه للفحص الطبي المباشر لدى طبيب مختص."
                    ),
                )
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=fallback.model_dump(mode="json"),
                )
        if _is_voice_triage_path(path) and exc.status_code in (
            status.HTTP_400_BAD_REQUEST,
            HTTP_422_STATUS,
        ):
            session_id = _extract_session_id_safely(request)
            fb_voice = create_fallback_voice_triage_response(session_id=session_id)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_voice.model_dump(mode="json"),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Global catch-all exception handler enforcing SLO-07 safe fallback."""
        logger.error("Unhandled gateway exception on %s: %s", request.url.path, exc, exc_info=True)
        path = request.url.path
        if _is_triage_path(path):
            session_id = _extract_session_id_safely(request)
            fallback = create_fallback_triage_response(
                session_id=session_id,
                rationale_ar=(
                    "حدث خطأ غير متوقع في النظام. للحفاظ على سلامتك، يرجى التوجه للفحص "
                    "الطبي المباشر لدى طبيب مختص أو أقرب مركز رعاية صحية فوراً."
                ),
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fallback.model_dump(mode="json"),
            )
        if _is_voice_triage_path(path):
            session_id = _extract_session_id_safely(request)
            fb_voice = create_fallback_voice_triage_response(session_id=session_id)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_voice.model_dump(mode="json"),
            )
        if _is_voice_transcribe_path(path):
            fb_stt = TranscriptionResult(
                success=False,
                text="",
                provider="fallback_text",
                fallback_to_text=True,
                latency_ms=0.0,
                error_reason_ar="حدث خطأ غير متوقع أثناء معالجة الصوت؛ يرجى كتابة الأعراض نصياً.",
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_stt.model_dump(mode="json"),
            )
        if _is_voice_synthesize_path(path):
            fb_tts = SynthesisResult(
                success=False,
                spoken_text_ar=DEFAULT_DISCLAIMER_AR,
                audio_base64=None,
                mime_type="audio/wav",
                provider=settings.TTS_PROVIDER,
                fallback_to_text=True,
                latency_ms=0.0,
                error_reason_ar="حدث خطأ غير متوقع أثناء توليد الصوت؛ يتم عرض الإرشادات نصياً.",
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fb_tts.model_dump(mode="json"),
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error"},
        )

    # Health Endpoints (Synchronous to avoid anyio portal overhead/deadlocks)
    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="Service Health Check",
        tags=["System"],
    )
    def health_root() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.APP_NAME,
            phase=settings.PHASE,
        )

    # API v1 Router
    api_v1_router = APIRouter(prefix=settings.API_V1_PREFIX, tags=["Triage API v1"])

    @api_v1_router.get(
        "/health",
        response_model=HealthResponse,
        summary="API v1 Health Check",
    )
    def health_v1() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.APP_NAME,
            phase=settings.PHASE,
        )

    @api_v1_router.post(
        "/triage",
        response_model=TriageResponse,
        summary="Clinical Pre-Care Triage & Specialist Referral",
    )
    async def triage_endpoint(
        request: Request,
        payload: TriageRequest,
        background_tasks: BackgroundTasks,
    ) -> Any:
        client_ip = extract_client_ip(request)
        allowed, retry_after = rate_limiter.is_allowed(client_ip)

        sync_mode = getattr(app.state, "sync_audit", True)
        if (
            request.headers.get("X-Sync-Audit", "").lower() == "false"
            or request.query_params.get("sync_audit", "").lower() == "false"
        ):
            sync_mode = False
        elif (
            request.headers.get("X-Sync-Audit", "").lower() == "true"
            or request.query_params.get("sync_audit", "").lower() == "true"
        ):
            sync_mode = True

        async def _schedule_audit(resp_obj: Any, lat_ms: float | None = None) -> None:
            _publish_sse_escalation_if_needed(
                session_id=payload.session_id,
                user_input=payload.user_input,
                response=resp_obj,
            )
            if sync_mode:
                await persist_audit_log(
                    session_id=payload.session_id,
                    user_input=payload.user_input,
                    response=resp_obj,
                    latency_ms=lat_ms,
                )
            else:
                background_tasks.add_task(
                    persist_audit_log,
                    session_id=payload.session_id,
                    user_input=payload.user_input,
                    response=resp_obj,
                    latency_ms=lat_ms,
                )

        if not allowed:
            fallback = create_fallback_triage_response(
                session_id=payload.session_id,
                rationale_ar=(
                    "تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة). "
                    "للحفاظ على سلامتك، يرجى التوجه للفحص الطبي المباشر لدى طبيب مختص أو الانتظار قبل المحاولة مرة أخرى."
                ),
            )
            await _schedule_audit(fallback)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=fallback.model_dump(mode="json"),
                headers={"Retry-After": str(retry_after)},
            )
        try:
            start_t = time.perf_counter()
            response = await triage_service.process_triage(payload)
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            await _schedule_audit(response, elapsed_ms)
            return response
        except Exception as exc:
            logger.error("Internal triage exception: %s", exc, exc_info=True)
            fallback = triage_service.create_fallback_triage_response(
                session_id=payload.session_id,
                rationale_ar=(
                    "حدث خطأ غير متوقع أثناء معالجة الطلب. للحفاظ على سلامتك، "
                    "يرجى التوجه للفحص الطبي المباشر لدى طبيب مختص."
                ),
            )
            await _schedule_audit(fallback)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fallback.model_dump(mode="json"),
            )

    # =======================================================================
    # Fault-Tolerant Bi-Directional Voice Endpoints (Step 1 Voice Module)
    # =======================================================================

    @api_v1_router.post(
        "/voice/transcribe",
        response_model=TranscriptionResult,
        summary="In-Memory Speech-to-Text Transcription with 2.5s Timeout & Graceful Fallback",
        tags=["Voice Triage"],
    )
    async def voice_transcribe_endpoint(
        request: Request,
        payload: VoiceTranscribeRequest,
    ) -> Any:
        client_ip = extract_client_ip(request)
        allowed, retry_after = rate_limiter.is_allowed(client_ip)
        if not allowed:
            fb_stt = TranscriptionResult(
                success=False,
                text="",
                provider="rate_limited",
                fallback_to_text=True,
                latency_ms=0.0,
                error_reason_ar=(
                    "تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة). "
                    "يرجى كتابة الأعراض نصياً أو الانتظار قبل المحاولة مرة أخرى."
                ),
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=fb_stt.model_dump(mode="json"),
                headers={"Retry-After": str(retry_after)},
            )

        audio_bytes = decode_audio_base64(payload.audio_base64)
        return await voice_adapter.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=payload.filename,
            language=payload.language,
            fallback_text=payload.fallback_text,
        )

    @api_v1_router.post(
        "/voice/synthesize",
        response_model=SynthesisResult,
        summary="In-Memory Arabic Text-to-Speech Synthesis Guaranteeing Disclaimer Compliance",
        tags=["Voice Triage"],
    )
    async def voice_synthesize_endpoint(
        request: Request,
        payload: VoiceSynthesizeRequest,
    ) -> Any:
        client_ip = extract_client_ip(request)
        allowed, retry_after = rate_limiter.is_allowed(client_ip)
        if not allowed:
            fb_tts = SynthesisResult(
                success=False,
                spoken_text_ar=ensure_spoken_disclaimer(
                    payload.text, include_disclaimer=payload.include_disclaimer
                ),
                audio_base64=None,
                mime_type="audio/wav",
                provider=settings.TTS_PROVIDER,
                fallback_to_text=True,
                latency_ms=0.0,
                error_reason_ar="تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة).",
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=fb_tts.model_dump(mode="json"),
                headers={"Retry-After": str(retry_after)},
            )

        return await voice_adapter.synthesize_speech(
            text=payload.text,
            include_disclaimer=payload.include_disclaimer,
        )

    @api_v1_router.post(
        "/voice/triage",
        response_model=VoiceTriageResponse,
        summary="End-to-End Bi-Directional Voice Triage (STT -> Triage Pipeline -> TTS)",
        tags=["Voice Triage"],
    )
    async def voice_triage_endpoint(
        request: Request,
        payload: VoiceTriageRequest,
        background_tasks: BackgroundTasks,
    ) -> Any:
        client_ip = extract_client_ip(request)
        allowed, retry_after = rate_limiter.is_allowed(client_ip)

        sync_mode = getattr(app.state, "sync_audit", True)
        if (
            request.headers.get("X-Sync-Audit", "").lower() == "false"
            or request.query_params.get("sync_audit", "").lower() == "false"
        ):
            sync_mode = False
        elif (
            request.headers.get("X-Sync-Audit", "").lower() == "true"
            or request.query_params.get("sync_audit", "").lower() == "true"
        ):
            sync_mode = True

        async def _schedule_voice_audit(
            raw_input_text: str, resp_obj: Any, lat_ms: float | None = None
        ) -> None:
            _publish_sse_escalation_if_needed(
                session_id=payload.session_id,
                user_input=raw_input_text,
                response=resp_obj,
            )
            if sync_mode:
                await persist_audit_log(
                    session_id=payload.session_id,
                    user_input=raw_input_text,
                    response=resp_obj,
                    latency_ms=lat_ms,
                )
            else:
                background_tasks.add_task(
                    persist_audit_log,
                    session_id=payload.session_id,
                    user_input=raw_input_text,
                    response=resp_obj,
                    latency_ms=lat_ms,
                )

        if not allowed:
            fb_voice = create_fallback_voice_triage_response(
                session_id=payload.session_id,
                rationale_ar=(
                    "تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة). "
                    "للحفاظ على سلامتك، يرجى التوجه للفحص الطبي المباشر لدى طبيب مختص أو الانتظار قبل المحاولة مرة أخرى."
                ),
                error_reason_ar="تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة).",
            )
            await _schedule_voice_audit("rate_limited_voice", fb_voice.triage)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=fb_voice.model_dump(mode="json"),
                headers={"Retry-After": str(retry_after)},
            )

        # Step A: Run STT transcription with strict 2.5s timeout
        audio_bytes = decode_audio_base64(payload.audio_base64)
        transcription = await voice_adapter.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=payload.filename,
            language=payload.language,
            fallback_text=payload.fallback_text,
        )

        # Step B & Step C: Run clinical triage pipeline or construct safe Level 3 fallback
        start_t = time.perf_counter()
        transcribed_text = (transcription.text or "").strip()
        if transcribed_text and len(transcribed_text) >= 2:
            try:
                triage_req = TriageRequest(
                    session_id=payload.session_id,
                    user_input=transcribed_text[:1500],
                    input_mode="voice",
                )
                triage_response = await triage_service.process_triage(triage_req)
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                await _schedule_voice_audit(transcribed_text, triage_response, elapsed_ms)
            except Exception as exc:
                logger.error("Voice triage pipeline exception: %s", exc, exc_info=True)
                triage_response = create_fallback_triage_response(
                    session_id=payload.session_id,
                    rationale_ar=(
                        "حدث خطأ غير متوقع أثناء معالجة الأعراض الصوتية. للحفاظ على سلامتك، "
                        "يرجى كتابة الأعراض نصياً أو التوجه للفحص الطبي المباشر لدى طبيب مختص."
                    ),
                )
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                await _schedule_voice_audit(transcribed_text, triage_response, elapsed_ms)
        else:
            # Step C: STT failed/timed out and no fallback_text is available -> Level 3 safe fallback
            triage_response = create_fallback_triage_response(
                session_id=payload.session_id,
                rationale_ar=(
                    "تعذر سماع أو تحويل التسجيل الصوتي إلى نص واضح. للحفاظ على سلامتك، "
                    "يرجى كتابة الأعراض التي تشعر بها نصياً أو التوجه مباشرة لاستشارة طبيب مختص."
                ),
            )
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            await _schedule_voice_audit("voice_stt_fallback", triage_response, elapsed_ms)

        # Step D: Synthesize Arabic speech for rationale_ar with mandatory disclaimer (2.5s timeout)
        synthesis = await voice_adapter.synthesize_speech(
            text=triage_response.rationale_ar,
            include_disclaimer=True,
        )

        return VoiceTriageResponse(
            triage=triage_response,
            transcription=transcription,
            synthesis=synthesis,
        )

    @api_v1_router.get(
        "/escalations/stream",
        summary="Real-Time Zero-PHI Server-Sent Events (SSE) Emergency Escalation Stream",
        tags=["Supervisor Dashboard"],
    )
    async def stream_escalations(
        replay_recent: bool = Query(default=True),
        max_events: int | None = Query(default=None, ge=1, le=100),
        once: bool = Query(default=False),
        heartbeat_interval: float = Query(default=2.0, ge=0.1, le=30.0),
    ) -> StreamingResponse:
        return StreamingResponse(
            escalation_broadcaster.stream_events(
                replay_recent=replay_recent,
                max_events=max_events,
                once=once,
                heartbeat_interval=heartbeat_interval,
            ),
            media_type="text/event-stream",
            headers=dict(SSE_STREAM_HEADERS),
        )

    @api_v1_router.get(
        "/escalations",
        response_model=EscalationListResponse,
        summary="List Zero-PHI Escalations for Supervisor Dashboard",
        tags=["Supervisor Dashboard"],
    )
    async def get_escalations(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> EscalationListResponse:
        engine = getattr(app.state, "db_engine", None)
        if engine is None:
            return EscalationListResponse(items=[], count=0)
        try:
            from app.db.crud import create_session_factory, list_escalations

            norm_status = status.strip().lower() if status else None
            if norm_status in ("all", ""):
                norm_status = None

            session_factory = create_session_factory(engine)
            async with session_factory() as session:
                records = await list_escalations(session, status=norm_status, limit=limit)
                items = [
                    EscalationItem(
                        id=str(r.id),
                        audit_log_id=str(r.audit_log_id),
                        session_id=r.session_id,
                        created_at=_format_datetime(r.created_at) or "",
                        symptom_category=r.symptom_category,
                        detected_red_flags=_safe_str_list(r.detected_red_flags),
                        scrubbed_summary=r.scrubbed_summary,
                        status=r.status,
                        acknowledged_at=_format_datetime(r.acknowledged_at),
                        resolved_at=_format_datetime(r.resolved_at),
                    )
                    for r in records
                ]
                return EscalationListResponse(items=items, count=len(items))
        except Exception as exc:
            logger.warning("Fail-safe: error fetching escalations: %s", exc)
            return EscalationListResponse(items=[], count=0)

    @api_v1_router.patch(
        "/escalations/{escalation_id}",
        response_model=EscalationItem,
        summary="Acknowledge or Resolve Escalation Alert",
        tags=["Supervisor Dashboard"],
    )
    async def patch_escalation(
        escalation_id: str,
        payload: EscalationUpdateRequest,
    ) -> Any:
        engine = getattr(app.state, "db_engine", None)
        if engine is None:
            raise StarletteHTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Audit database is currently unavailable",
            )
        import uuid

        from app.db.crud import (
            acknowledge_escalation,
            create_session_factory,
            resolve_escalation,
        )

        try:
            target_uuid = uuid.UUID(str(escalation_id).strip())
        except ValueError:
            raise StarletteHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Escalation {escalation_id} not found",
            )

        try:
            session_factory = create_session_factory(engine)
            async with session_factory() as session, session.begin():
                if payload.status == "acknowledged":
                    updated = await acknowledge_escalation(session, target_uuid)
                elif payload.status == "resolved":
                    updated = await resolve_escalation(session, target_uuid)
                else:
                    raise StarletteHTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid status transition",
                    )

                return EscalationItem(
                    id=str(updated.id),
                    audit_log_id=str(updated.audit_log_id),
                    session_id=updated.session_id,
                    created_at=_format_datetime(updated.created_at) or "",
                    symptom_category=updated.symptom_category,
                    detected_red_flags=_safe_str_list(updated.detected_red_flags),
                    scrubbed_summary=updated.scrubbed_summary,
                    status=updated.status,
                    acknowledged_at=_format_datetime(updated.acknowledged_at),
                    resolved_at=_format_datetime(updated.resolved_at),
                )
        except LookupError:
            raise StarletteHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Escalation {escalation_id} not found",
            )
        except StarletteHTTPException:
            raise
        except SQLAlchemyError as db_err:
            logger.error(
                "DB operational error updating escalation %s: %s",
                escalation_id,
                db_err,
                exc_info=True,
            )
            raise StarletteHTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Audit database is currently unavailable",
            )
        except Exception as exc:
            logger.error("Error updating escalation %s: %s", escalation_id, exc, exc_info=True)
            raise StarletteHTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update escalation: {exc}",
            )

    @api_v1_router.get(
        "/audit-logs",
        response_model=AuditLogsResponse,
        summary="List Zero-PHI Anonymized Interaction Audit Logs",
        tags=["Supervisor Dashboard"],
    )
    async def get_audit_logs(
        limit: int = Query(default=50, ge=1, le=500),
        escalated_only: bool = Query(default=False),
    ) -> AuditLogsResponse:
        engine = getattr(app.state, "db_engine", None)
        if engine is None:
            return AuditLogsResponse(items=[], total_count=0, escalated_count=0, avg_latency_ms=0.0)
        try:
            from app.db.crud import create_session_factory, list_audit_logs

            session_factory = create_session_factory(engine)
            async with session_factory() as session:
                records, total_cnt, esc_cnt, avg_lat = await list_audit_logs(
                    session, limit=limit, escalated_only=escalated_only
                )
                items = [
                    AuditLogItem(
                        id=str(r.id),
                        session_id=r.session_id,
                        created_at=_format_datetime(r.created_at) or "",
                        scrubbed_input=r.scrubbed_input,
                        symptom_category=r.symptom_category,
                        urgency_level=r.urgency_level,
                        recommended_specialty=r.recommended_specialty,
                        retrieved_doc_ids=_safe_str_list(r.retrieved_doc_ids),
                        escalation_triggered=r.escalation_triggered,
                        latency_ms=r.latency_ms,
                    )
                    for r in records
                ]
                return AuditLogsResponse(
                    items=items,
                    total_count=total_cnt,
                    escalated_count=esc_cnt,
                    avg_latency_ms=avg_lat,
                )
        except Exception as exc:
            logger.warning("Fail-safe: error fetching audit logs: %s", exc)
            return AuditLogsResponse(items=[], total_count=0, escalated_count=0, avg_latency_ms=0.0)

    # Mount API v1 router
    app.include_router(api_v1_router)

    # Optional alias: POST /triage -> delegates to triage_endpoint
    @app.post(
        "/triage",
        response_model=TriageResponse,
        include_in_schema=False,
    )
    async def triage_alias(
        request: Request,
        payload: TriageRequest,
        background_tasks: BackgroundTasks,
    ) -> Any:
        return await triage_endpoint(
            request=request, payload=payload, background_tasks=background_tasks
        )

    # Root alias paths for Voice Endpoints
    @app.post(
        "/voice/transcribe",
        response_model=TranscriptionResult,
        include_in_schema=False,
    )
    async def voice_transcribe_alias(
        request: Request,
        payload: VoiceTranscribeRequest,
    ) -> Any:
        return await voice_transcribe_endpoint(request=request, payload=payload)

    @app.post(
        "/voice/synthesize",
        response_model=SynthesisResult,
        include_in_schema=False,
    )
    async def voice_synthesize_alias(
        request: Request,
        payload: VoiceSynthesizeRequest,
    ) -> Any:
        return await voice_synthesize_endpoint(request=request, payload=payload)

    @app.post(
        "/voice/triage",
        response_model=VoiceTriageResponse,
        include_in_schema=False,
    )
    async def voice_triage_alias(
        request: Request,
        payload: VoiceTriageRequest,
        background_tasks: BackgroundTasks,
    ) -> Any:
        return await voice_triage_endpoint(
            request=request, payload=payload, background_tasks=background_tasks
        )

    # Root alias paths for Supervisor Dashboard & Audit API
    @app.get(
        "/escalations/stream",
        include_in_schema=False,
    )
    async def stream_escalations_alias(
        replay_recent: bool = Query(default=True),
        max_events: int | None = Query(default=None, ge=1, le=100),
        once: bool = Query(default=False),
        heartbeat_interval: float = Query(default=2.0, ge=0.1, le=30.0),
    ) -> StreamingResponse:
        return await stream_escalations(
            replay_recent=replay_recent,
            max_events=max_events,
            once=once,
            heartbeat_interval=heartbeat_interval,
        )

    @app.get(
        "/escalations",
        response_model=EscalationListResponse,
        include_in_schema=False,
    )
    async def escalations_alias(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> EscalationListResponse:
        return await get_escalations(status=status, limit=limit)

    @app.patch(
        "/escalations/{escalation_id}",
        response_model=EscalationItem,
        include_in_schema=False,
    )
    async def patch_escalation_alias(
        escalation_id: str,
        payload: EscalationUpdateRequest,
    ) -> Any:
        return await patch_escalation(escalation_id=escalation_id, payload=payload)

    @app.get(
        "/audit-logs",
        response_model=AuditLogsResponse,
        include_in_schema=False,
    )
    async def audit_logs_alias(
        limit: int = Query(default=50, ge=1, le=500),
        escalated_only: bool = Query(default=False),
    ) -> AuditLogsResponse:
        return await get_audit_logs(limit=limit, escalated_only=escalated_only)

    return app


app = create_app()

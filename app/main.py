"""FastAPI Gateway Core for ShefaGuide AI.

Exposes health endpoints, deterministic clinical triage, in-memory sliding-window
rate limiting, and global safe fallback handlers.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.rate_limiter import extract_client_ip, rate_limiter
from app.schemas.triage import TriageRequest, TriageResponse
from app.services import triage_service
from app.services.triage_service import create_fallback_triage_response

logger = logging.getLogger("shefaguide.gateway")


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
        from app.schemas.triage import SymptomCategory, UrgencyLevel

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
        if len(safe_sid) < 8:
            safe_sid = f"session_{safe_sid}"[:64]
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
    """Check if the request path targets clinical triage."""
    return (
        path == "/triage"
        or path == f"{settings.API_V1_PREFIX}/triage"
        or path.startswith(f"{settings.API_V1_PREFIX}/triage/")
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
        if getattr(app.state, "db_engine", None) is not None:
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

    # Attach shared rate limiter to application state
    app.state.rate_limiter = rate_limiter

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
        """Catch malformed payloads or schema validation errors and return Level 3 fallback."""
        if _is_triage_path(request.url.path):
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
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle HTTP errors on triage routes safely."""
        if _is_triage_path(request.url.path):
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
                status.HTTP_422_UNPROCESSABLE_ENTITY,
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
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Global catch-all exception handler enforcing SLO-07 safe fallback."""
        logger.error("Unhandled gateway exception on %s: %s", request.url.path, exc, exc_info=True)
        if _is_triage_path(request.url.path):
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
        if not allowed:
            fallback = create_fallback_triage_response(
                session_id=payload.session_id,
                rationale_ar=(
                    "تم تجاوز الحد الأقصى للطلبات المسموح بها (15 طلب في الدقيقة). "
                    "للحفاظ على سلامتك، يرجى التوجه للفحص الطبي المباشر لدى طبيب مختص أو الانتظار قبل المحاولة مرة أخرى."
                ),
            )
            background_tasks.add_task(
                persist_audit_log,
                session_id=payload.session_id,
                user_input=payload.user_input,
                response=fallback,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=fallback.model_dump(mode="json"),
                headers={"Retry-After": str(retry_after)},
            )
        try:
            start_t = time.perf_counter()
            response = await triage_service.process_triage(payload)
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            background_tasks.add_task(
                persist_audit_log,
                session_id=payload.session_id,
                user_input=payload.user_input,
                response=response,
                latency_ms=elapsed_ms,
            )
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
            background_tasks.add_task(
                persist_audit_log,
                session_id=payload.session_id,
                user_input=payload.user_input,
                response=fallback,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=fallback.model_dump(mode="json"),
            )

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

    return app


app = create_app()

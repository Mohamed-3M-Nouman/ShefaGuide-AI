"""Centralized application settings and configuration for ShefaGuide AI."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings for ShefaGuide AI."""

    # Application Metadata
    APP_NAME: str = Field(
        default="ShefaGuide AI",
        description="Application service name.",
    )
    APP_VERSION: str = Field(
        default="0.1.0",
        description="SemVer application version.",
    )
    PHASE: str = Field(
        default="walking-skeleton",
        description="Deployment or project phase identifier.",
    )

    # API Routing Prefix
    API_V1_PREFIX: str = Field(
        default="/api/v1",
        description="Prefix for API version 1 routes.",
    )

    # CORS Origins Configuration
    CORS_ORIGINS: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins list or wildcard.",
    )

    # Sliding-Window Rate Limiting Settings
    RATE_LIMIT: str = Field(
        default="15/minute",
        description="Human-readable / SlowAPI rate limit string.",
    )
    RATE_LIMIT_REQUESTS: int = Field(
        default=15,
        description="Maximum allowed requests per sliding window duration.",
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        description="Sliding window duration in seconds.",
    )

    # LLM & Agent Settings
    GEMINI_API_KEY: str = Field(
        default="",
        description="Google Gemini API key for non-emergency triage agent.",
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.5-flash",
        description="Default Gemini model identifier.",
    )

    # Vector Database (Qdrant) Settings
    QDRANT_URL: str = Field(
        default="http://localhost:6333",
        description="Qdrant vector database endpoint URL.",
    )
    QDRANT_COLLECTION: str = Field(
        default="shefaguide_medical_chunks",
        description="Qdrant collection name for clinical guideline chunks.",
    )

    # Audit Database (PostgreSQL) Settings
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://shefaguide:shefaguide_secret@localhost:5432/shefaguide_audit",
        description="Async SQLAlchemy PostgreSQL connection URL for Zero-PHI audit logging.",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, value: Any) -> list[str]:
        """Support comma-separated strings or JSON arrays in environment variables."""
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [orig.strip() for orig in value.split(",") if orig.strip()]
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()

# Direct module-level exports for convenience
APP_NAME = settings.APP_NAME
APP_VERSION = settings.APP_VERSION
PHASE = settings.PHASE
API_V1_PREFIX = settings.API_V1_PREFIX
CORS_ORIGINS = settings.CORS_ORIGINS
RATE_LIMIT = settings.RATE_LIMIT
RATE_LIMIT_REQUESTS = settings.RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS = settings.RATE_LIMIT_WINDOW_SECONDS
GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_MODEL = settings.GEMINI_MODEL
QDRANT_URL = settings.QDRANT_URL
QDRANT_COLLECTION = settings.QDRANT_COLLECTION
DATABASE_URL = settings.DATABASE_URL

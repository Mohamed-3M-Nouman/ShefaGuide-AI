"""Step 2 tests for Container Infrastructure (Dockerfile, docker-compose.yml), .env.example, and config."""

from __future__ import annotations

from pathlib import Path

from app.core.config import (
    DATABASE_URL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RATE_LIMIT,
    settings,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_step2_infrastructure_files_exist_and_non_empty() -> None:
    """1. Verify Dockerfile, docker-compose.yml, .env.example, and requirements.txt exist and are non-empty."""
    required_files = [
        "Dockerfile",
        "docker-compose.yml",
        ".env.example",
        "requirements.txt",
    ]
    for filename in required_files:
        file_path = PROJECT_ROOT / filename
        assert file_path.exists(), f"Missing required infrastructure file: {filename}"
        content = file_path.read_text(encoding="utf-8").strip()
        assert len(content) > 0, f"Infrastructure file {filename} is empty"


def test_dockerfile_defines_python313_and_uvicorn_entrypoint() -> None:
    """Verify Dockerfile uses python:3.13-slim, exposes 8000, and runs uvicorn app.main:app."""
    dockerfile_text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.13-slim" in dockerfile_text
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile_text
    assert "PYTHONUNBUFFERED=1" in dockerfile_text
    assert "WORKDIR /app" in dockerfile_text
    assert "EXPOSE 8000" in dockerfile_text
    assert "app.main:app" in dockerfile_text


def test_docker_compose_defines_services_ports_and_volumes() -> None:
    """2. Verify docker-compose.yml defines fastapi-backend, qdrant, postgres, ports, and volumes."""
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    # Services and container names
    assert "fastapi-backend:" in compose_text
    assert "shefaguide-api" in compose_text
    assert "qdrant:" in compose_text
    assert "qdrant/qdrant:latest" in compose_text
    assert "postgres:" in compose_text
    assert "postgres:16-alpine" in compose_text

    # Ports
    assert "8000:8000" in compose_text
    assert "6333:6333" in compose_text
    assert "6334:6334" in compose_text
    assert "5432:5432" in compose_text

    # Persistent volumes and healthchecks
    assert "qdrant_storage:" in compose_text
    assert "postgres_data:" in compose_text
    assert "pg_isready -U shefaguide -d shefaguide_audit" in compose_text
    assert "http://localhost:8000/health" in compose_text


def test_env_example_documents_all_required_keys() -> None:
    """3. Verify .env.example contains all required environment keys."""
    env_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    required_keys = [
        "APP_NAME=",
        "APP_VERSION=",
        "PHASE=",
        "API_V1_PREFIX=",
        "RATE_LIMIT=",
        "RATE_LIMIT_REQUESTS=",
        "RATE_LIMIT_WINDOW_SECONDS=",
        "CORS_ORIGINS=",
        "GEMINI_API_KEY=",
        "GEMINI_MODEL=",
        "QDRANT_URL=",
        "QDRANT_COLLECTION=",
        "DATABASE_URL=",
    ]
    for key in required_keys:
        assert key in env_text, f"Missing {key} in .env.example"


def test_config_exposes_step2_settings_and_defaults() -> None:
    """4. Verify app/core/config.py exposes GEMINI_MODEL, QDRANT_URL, QDRANT_COLLECTION, and DATABASE_URL."""
    assert settings.GEMINI_MODEL == "gemini-2.5-flash"
    assert settings.QDRANT_URL == "http://localhost:6333"
    assert settings.QDRANT_COLLECTION == "shefaguide_medical_chunks"
    assert (
        settings.DATABASE_URL
        == "postgresql+asyncpg://shefaguide:shefaguide_secret@localhost:5432/shefaguide_audit"
    )
    assert settings.RATE_LIMIT == "15/minute"
    assert isinstance(settings.GEMINI_API_KEY, str)

    # Module-level exports
    assert GEMINI_MODEL == "gemini-2.5-flash"
    assert QDRANT_URL == "http://localhost:6333"
    assert QDRANT_COLLECTION == "shefaguide_medical_chunks"
    assert (
        DATABASE_URL
        == "postgresql+asyncpg://shefaguide:shefaguide_secret@localhost:5432/shefaguide_audit"
    )
    assert RATE_LIMIT == "15/minute"
    assert isinstance(GEMINI_API_KEY, str)


def test_requirements_txt_contains_core_dependencies() -> None:
    """Verify requirements.txt lists core gateway, agent, vector DB, and async DB packages."""
    req_text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    expected_packages = [
        "fastapi",
        "uvicorn[standard]",
        "pydantic",
        "pydantic-settings",
        "slowapi",
        "httpx",
        "pytest",
        "pytest-asyncio",
        "langgraph",
        "langchain-core",
        "langchain-google-genai",
        "qdrant-client",
        "sqlalchemy[asyncio]",
        "asyncpg",
        "ruff",
    ]
    for pkg in expected_packages:
        assert pkg in req_text, f"Missing dependency {pkg} in requirements.txt"

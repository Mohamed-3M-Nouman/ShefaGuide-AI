"""Shared pytest fixtures: isolate ephemeral session store and attach default supervisor test header."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from starlette.testclient import TestClient

import app.agent.tools as agent_tools
from app.agent.session_store import session_store
from app.core.config import settings

_ORIG_TESTCLIENT_INIT = TestClient.__init__


def _patched_testclient_init(self: TestClient, *args: Any, **kwargs: Any) -> None:
    if kwargs.get("headers") is None:
        kwargs["headers"] = {"X-Supervisor-Key": settings.SUPERVISOR_API_KEY}
    _ORIG_TESTCLIENT_INIT(self, *args, **kwargs)


TestClient.__init__ = _patched_testclient_init  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def reset_session_store(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Reset session store and isolate unit/gateway tests from live .env LLM API calls."""
    monkeypatch.setattr(agent_tools, "_has_live_gemini_key", lambda: False)
    monkeypatch.setattr(agent_tools, "_has_live_sovereigneg_key", lambda: False)
    session_store.reset()
    yield
    session_store.reset()

"""Shared pytest fixtures: isolate the process-wide ephemeral session store between tests.

Several gateway tests reuse static `session_id`s; since multi-turn merging is keyed by
`session_id`, the singleton `session_store` must start empty for every test.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

import app.agent.tools as agent_tools
from app.agent.session_store import session_store


@pytest.fixture(autouse=True)
def reset_session_store(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Reset session store and isolate unit/gateway tests from live .env LLM API calls."""
    monkeypatch.setattr(agent_tools, "_has_live_gemini_key", lambda: False)
    monkeypatch.setattr(agent_tools, "_has_live_sovereigneg_key", lambda: False)
    session_store.reset()
    yield
    session_store.reset()

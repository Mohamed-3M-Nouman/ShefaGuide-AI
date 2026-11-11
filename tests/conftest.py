"""Shared pytest fixtures: isolate the process-wide ephemeral session store between tests.

Several gateway tests reuse static `session_id`s; since multi-turn merging is keyed by
`session_id`, the singleton `session_store` must start empty for every test.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.agent.session_store import session_store


@pytest.fixture(autouse=True)
def reset_session_store() -> Generator[None, None, None]:
    """Reset the in-memory session store before and after every test (zero cross-test leakage)."""
    session_store.reset()
    yield
    session_store.reset()

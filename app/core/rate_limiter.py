"""In-memory sliding-window rate limiter for ShefaGuide AI."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import NamedTuple

from starlette.requests import Request

from app.core.config import settings


class RateLimitResult(NamedTuple):
    """Result details of a rate-limit check."""

    allowed: bool
    retry_after: int
    current_requests: int
    max_requests: int


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter enforcing request quotas."""

    def __init__(
        self,
        requests_per_window: int = settings.RATE_LIMIT_REQUESTS,
        window_seconds: int = settings.RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._history: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def is_allowed(self, client_id: str) -> tuple[bool, int]:
        """Check whether a request from client_id is permitted within the sliding window.

        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._history[client_id]

            # Evict timestamps older than the sliding window boundary
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.requests_per_window:
                earliest = timestamps[0]
                retry_after = max(1, int(self.window_seconds - (now - earliest) + 1))
                return False, retry_after

            timestamps.append(now)
            return True, 0

    def check(self, client_id: str) -> RateLimitResult:
        """Inspect rate limit status for client_id."""
        allowed, retry_after = self.is_allowed(client_id)
        with self._lock:
            count = len(self._history[client_id])
        return RateLimitResult(
            allowed=allowed,
            retry_after=retry_after,
            current_requests=count,
            max_requests=self.requests_per_window,
        )

    def reset(self, client_id: str | None = None) -> None:
        """Reset tracking history across all clients or for a specific client_id."""
        with self._lock:
            if client_id is None:
                self._history.clear()
            else:
                self._history.pop(client_id, None)


def extract_client_ip(request: Request) -> str:
    """Extract client IP address from request headers or socket address."""
    # Check X-Forwarded-For (first IP in chain is original client)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return client_ip

    # Check X-Real-IP
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    # Fallback to direct client host
    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


# Default module-level rate limiter singleton
rate_limiter = SlidingWindowRateLimiter()

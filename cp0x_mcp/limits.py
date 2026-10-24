"""Sliding-window limits for requests from each caller."""

import math
import time
from collections import deque
from typing import Callable


class RateLimiter:
    """Count accepted requests in the last sixty seconds per key."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic):
        if per_minute < 1:
            raise ValueError("per_minute must be at least 1")
        self._per_minute = per_minute
        self._clock = clock
        self._windows: dict[str, deque[float]] = {}
        self._events: deque[tuple[float, str]] = deque()

    def allow(self, key: str) -> tuple[bool, int]:
        """Accept a request or return the seconds until a slot becomes free."""
        now = self._clock()
        # Expire every idle key as well as the key making this request.
        while self._events and self._events[0][0] <= now - 60:
            _, expired_key = self._events.popleft()
            window = self._windows[expired_key]
            window.popleft()
            if not window:
                del self._windows[expired_key]

        window = self._windows.setdefault(key, deque())
        if len(window) >= self._per_minute:
            return False, max(1, min(60, math.ceil(window[0] + 60 - now)))
        window.append(now)
        self._events.append((now, key))
        return True, 0

"""Instance-local caching, upstream budgets, and host throttle backoff."""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Callable
from urllib.parse import urlsplit


class UpstreamError(Exception):
    """An upstream request failed and no cached response is available."""

    def __init__(self, message: str, retry_after_s: int | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class UpstreamThrottled(Exception):
    """The upstream host requested a pause before further requests."""

    def __init__(self, retry_after_s: float, url: str = ""):
        super().__init__(f"Upstream throttled {url}: retry after {retry_after_s} seconds")
        self.retry_after_s = retry_after_s
        self.url = url


@dataclass
class Fetched:
    data: Any
    stale: bool
    fetched_at: float
    fetched_wall: float


class Fetcher:
    """Share cache and per-host request limits safely across worker threads.

    Negative entries live at most negative_ttl_s and are pruned on every write.
    Budgeted attempts bound live entries per host to
    budget_per_minute * ceil(negative_ttl_s / 60), without a separate size cap.
    """

    def __init__(
        self,
        get_json: Callable[[str], Any],
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        budget_per_minute: int = 45,
        negative_ttl_s: float = 30,
    ):
        self._get_json = get_json
        self._clock = clock
        self._wall = wall
        self._budget_per_minute = budget_per_minute
        self._negative_ttl_s = negative_ttl_s
        self._lock = threading.Lock()
        self._cache: dict[str, Fetched] = {}
        self._calls: dict[str, deque[float]] = {}
        self._backoff_until: dict[str, float] = {}
        self._negative: dict[str, tuple[float, str]] = {}

    def age_s(self, fetched: Fetched) -> int:
        return int(self._clock() - fetched.fetched_at)

    def stats(self) -> dict:
        with self._lock:
            now = self._clock()
            return {
                "cached": len(self._cache),
                "negative": sum(until > now for until, _ in self._negative.values()),
                "backing_off": sum(until > now for until in self._backoff_until.values()),
            }

    @staticmethod
    def _fallback(cached: Fetched | None, message: str, retry_after_s: int | None = None) -> Fetched:
        if cached is not None:
            return replace(cached, stale=True)
        raise UpstreamError(message, retry_after_s=retry_after_s)

    def get(self, url: str, ttl_s: float) -> Fetched:
        host = urlsplit(url).netloc
        with self._lock:
            now = self._clock()
            cached = self._cache.get(url)
            if cached is not None and now - cached.fetched_at < ttl_s:
                return cached
            backoff_until = self._backoff_until.get(host, now)
            if now < backoff_until:
                return self._fallback(
                    cached, f"Upstream backoff for {url}",
                    max(1, math.ceil(backoff_until - now)),
                )
            negative = self._negative.get(url)
            if negative is not None:
                until, message = negative
                if now < until:
                    return self._fallback(cached, message, max(1, math.ceil(until - now)))
                self._negative.pop(url)
            calls = self._calls.setdefault(host, deque())
            while calls and calls[0] <= now - 60:
                calls.popleft()
            if len(calls) >= self._budget_per_minute:
                return self._fallback(
                    cached, f"Upstream request budget exhausted for {url}",
                    max(1, math.ceil(calls[0] + 60 - now)),
                )
            # Only actual upstream attempts, including failed ones, consume budget.
            calls.append(now)
        try:
            data = self._get_json(url)
        except UpstreamThrottled as exc:
            with self._lock:
                now = self._clock()
                backoff_until = max(self._backoff_until.get(host, now), now + exc.retry_after_s)
                self._backoff_until[host] = backoff_until
                cached = self._cache.get(url)
                if cached is not None and now - cached.fetched_at < ttl_s:
                    return cached
                return self._fallback(
                    cached, f"Upstream throttled {url}: {exc}",
                    max(1, math.ceil(backoff_until - now)),
                )
        except Exception as exc:
            message = f"Failed to fetch {url}: {exc}"
            with self._lock:
                now = self._clock()
                cached = self._cache.get(url)
                if cached is not None and now - cached.fetched_at < ttl_s:
                    return cached
                if cached is None:
                    expired = [key for key, (until, _) in self._negative.items() if until <= now]
                    for key in expired:
                        del self._negative[key]
                    self._negative[url] = (now + self._negative_ttl_s, message)
                return self._fallback(cached, message)
        with self._lock:
            fetched = Fetched(
                data, stale=False, fetched_at=self._clock(), fetched_wall=self._wall()
            )
            self._cache[url] = fetched
            self._negative.pop(url, None)
            return fetched

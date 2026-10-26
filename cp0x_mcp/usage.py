"""In-memory daily aggregate tool-call counts by client application."""

import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Callable


def normalize_client(name: str | None) -> str:
    """Return a bounded client name containing only safe ASCII characters."""
    normalized = re.sub(r"[^a-z0-9._-]", "-", (name or "").lower())[:64]
    return normalized if re.search(r"[a-z0-9]", normalized) else "unknown"


class UsageCounter:
    """Keep aggregate counts within a rolling window of UTC calendar days."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        retention_days: int = 30,
        max_clients_per_day: int = 50,
    ):
        self._now = now
        self._retention_days = retention_days
        self._max_clients_per_day = max_clients_per_day
        self.started_at = now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._days: dict[str, dict[str, dict[str, int]]] = {}

    def _prune(self, today: date) -> None:
        cutoff = (today - timedelta(days=self._retention_days - 1)).isoformat()
        for day in list(self._days):
            if day < cutoff:
                del self._days[day]

    def record(self, tool: str, client: str | None) -> None:
        """Count a tool call, folding excess daily client names into other."""
        today = self._now().astimezone(timezone.utc).date()
        self._prune(today)
        tools = self._days.setdefault(today.isoformat(), {})
        client = normalize_client(client)
        clients = {name for counts in tools.values() for name in counts}
        if client not in clients and len(clients) >= self._max_clients_per_day:
            client = "other"
        counts = tools.setdefault(tool, {})
        counts[client] = counts.get(client, 0) + 1

    def snapshot(self) -> dict:
        """Return an independent copy of the retained aggregate counts."""
        self._prune(self._now().astimezone(timezone.utc).date())
        return {"started_at": self.started_at, "days": deepcopy(self._days)}

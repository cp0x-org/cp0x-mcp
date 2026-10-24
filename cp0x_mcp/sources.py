"""Public upstream endpoints and cache lifetimes."""

import re

DEALS_URL = "https://cp0x.com/api/v1/deals"
MONITOR_INTERFACES_URL = (
    "https://raw.githubusercontent.com/cp0x-org/pi-restricted-interfaces/"
    "main/monitor/current/catalog/interfaces.json"
)
MONITOR_OBSERVATIONS_URL = (
    "https://raw.githubusercontent.com/cp0x-org/pi-restricted-interfaces/"
    "main/monitor/current/catalog/observations.json"
)
FACILITATORS_URL = "https://x402-api.cp0x.com/api/free/facilitators"
RESOURCES_URL = "https://x402-api.cp0x.com/api/free/cp0x-resources"
GITHUB_REPOS_URL = "https://api.github.com/orgs/cp0x-org/repos?per_page=100&type=public&sort=pushed"

TTL_DEALS_S = 60
TTL_RACES_S = 60
TTL_MONITOR_S = 600
TTL_X402_S = 300
TTL_GITHUB_S = 600
UPSTREAM_BUDGET_PER_MINUTE = 45


def race_url(slug: str, race_code: str) -> str:
    for name, value in (("slug", slug), ("race_code", race_code)):
        if not isinstance(value, str) or re.fullmatch(r"[a-z0-9_-]{1,64}", value) is None:
            raise ValueError(f"invalid {name}")
    return f"{DEALS_URL}/{slug}/races/{race_code}"

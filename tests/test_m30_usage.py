"""m30: daily aggregate usage counts per tool and client application, published at /usage; no IPs, arguments or single calls."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 10, 26, 3, 10, 5, tzinfo=timezone.utc)


class FakeNow:
    def __init__(self, value: datetime = START):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def counter(now=None, **kwargs):
    from cp0x_mcp.usage import UsageCounter

    return UsageCounter(now=now or FakeNow(), **kwargs)


def call_tools(server, client_name, calls, mode="legacy"):
    from mcp.client.client import Client
    import mcp.types as t

    async def go():
        async with Client(server, client_info=t.Implementation(name=client_name, version="1"), mode=mode) as client:
            for name, arguments in calls:
                await client.call_tool(name, arguments)

    anyio.run(go)


def get(app, path):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.cp0x.com") as client:
            return await client.get(path)

    return anyio.run(go)


@pytest.mark.parametrize("raw, expected", [
    ("Claude-AI Test", "claude-ai-test"),
    ("openai-mcp", "openai-mcp"),
    ("Cursor/1.2 (beta)", "cursor-1.2--beta-"),
    ("x" * 80, "x" * 64),
    ("", "unknown"),
    ("   ", "unknown"),
    ("!!!", "unknown"),
    (None, "unknown"),
])
def test_normalize_client(raw, expected):
    from cp0x_mcp.usage import normalize_client

    assert normalize_client(raw) == expected


def test_snapshot_counts_per_day_tool_and_client():
    c = counter()
    c.record("list_deals", "Claude-AI Test")
    c.record("list_deals", "Claude-AI Test")
    c.record("get_deal", None)
    assert c.snapshot() == {
        "started_at": "2026-10-26T03:10:05Z",
        "days": {"2026-10-26": {"list_deals": {"claude-ai-test": 2}, "get_deal": {"unknown": 1}}},
    }


def test_days_roll_at_utc_midnight():
    now = FakeNow(datetime(2026, 10, 26, 23, 59, 59, tzinfo=timezone.utc))
    c = counter(now)
    c.record("list_races", "a")
    now.advance(seconds=1)
    c.record("list_races", "a")
    assert c.snapshot()["days"] == {"2026-10-26": {"list_races": {"a": 1}}, "2026-10-27": {"list_races": {"a": 1}}}


def test_retention_keeps_the_last_30_days():
    now = FakeNow()
    c = counter(now)
    c.record("list_races", "a")
    now.advance(days=29)
    assert "2026-10-26" in c.snapshot()["days"]
    now.advance(days=1)
    assert "2026-10-26" not in c.snapshot()["days"]
    c.record("list_races", "a")
    assert list(c.snapshot()["days"]) == ["2026-11-25"]


def test_client_cap_per_day_folds_new_names_into_other():
    c = counter(max_clients_per_day=3)
    for name in ("a", "b", "c", "d", "e"):
        c.record("list_deals", name)
    c.record("list_deals", "a")
    assert c.snapshot()["days"]["2026-10-26"]["list_deals"] == {"a": 2, "b": 1, "c": 1, "other": 2}


def test_snapshot_is_a_copy():
    c = counter()
    c.record("list_deals", "a")
    snap = c.snapshot()
    snap["days"]["2026-10-26"]["list_deals"]["a"] = 999
    assert c.snapshot()["days"]["2026-10-26"]["list_deals"]["a"] == 1


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_server_counts_tool_calls_by_client(service, mode):
    from cp0x_mcp.server import build_server

    usage = counter()
    server = build_server(service, usage=usage)
    call_tools(server, "Claude-AI Test", [("list_races", {}), ("list_races", {}), ("list_deals", {"limit": 1})], mode=mode)
    assert usage.snapshot()["days"]["2026-10-26"] == {
        "list_races": {"claude-ai-test": 2},
        "list_deals": {"claude-ai-test": 1},
    }


def test_server_does_not_count_unknown_tools_or_other_methods(service):
    from cp0x_mcp.server import build_server

    usage = counter()
    server = build_server(service, usage=usage)
    call_tools(server, "probe", [("no_such_tool", {}), ("list_races", {})])
    assert usage.snapshot()["days"] == {"2026-10-26": {"list_races": {"probe": 1}}}


def test_server_without_usage_still_works(service):
    from mcp.server import MCPServer

    from cp0x_mcp.server import build_server

    server = build_server(service)
    assert type(server) is MCPServer
    call_tools(server, "probe", [("list_races", {})])


def test_usage_route_publishes_the_snapshot_without_arguments_or_ips(service):
    from cp0x_mcp.server import build_app, build_server

    usage = counter()
    server = build_server(service, usage=usage)
    call_tools(server, "Claude-AI Test", [("list_deals", {"query": "MARKER-7731"})])
    app = build_app(server, allowed_hosts=["mcp.cp0x.com"], usage=usage)
    response = get(app, "/usage")
    assert response.status_code == 200
    body = response.json()
    assert body == usage.snapshot()
    assert body["days"]["2026-10-26"] == {"list_deals": {"claude-ai-test": 1}}
    assert "MARKER-7731" not in response.text and "127.0.0.1" not in response.text


def test_usage_route_absent_without_counter(service):
    from cp0x_mcp.server import build_app, build_server

    app = build_app(build_server(service), allowed_hosts=["mcp.cp0x.com"])
    assert get(app, "/usage").status_code == 404


def test_usage_route_is_rate_limited(service):
    from cp0x_mcp.server import build_app, build_server

    usage = counter()
    app = build_app(build_server(service, usage=usage), allowed_hosts=["mcp.cp0x.com"], per_ip_per_minute=1, usage=usage)
    assert get(app, "/usage").status_code == 200
    assert get(app, "/usage").status_code == 429


def test_main_wires_one_counter_into_server_and_app(monkeypatch):
    import uvicorn

    from cp0x_mcp import server as server_module

    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.setdefault("app", app))
    server_module.main(["--transport", "http", "--allowed-host", "mcp.cp0x.com"])
    response = get(captured["app"], "/usage")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"started_at", "days"} and body["days"] == {}
    datetime.strptime(body["started_at"], "%Y-%m-%dT%H:%M:%SZ")


def test_privacy_and_readme_describe_usage_counts():
    privacy = (ROOT / "PRIVACY.md").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "does not record tool calls or their arguments" not in privacy
    assert "daily aggregate counts of tool calls per tool and per client application name" in privacy
    assert "It does not record IP addresses, arguments or individual calls." in privacy
    assert "/usage" in privacy
    assert "The HTTP routes are `/mcp`, `/health` and `/usage`." in readme

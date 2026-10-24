"""Contract of cp0x_mcp.server (MCP wrapper over Cp0xService) and cp0x_mcp.limits (per-caller rate limiter).

In-process checks use the SDK's MCPServer.list_tools()/call_tool(); the ASGI app is exercised with httpx.ASGITransport.
"""
import asyncio
import json

import httpx
import pytest

from tests.conftest import FakeClock

TOOL_NAMES = {
    "list_deals",
    "get_deal",
    "get_referral_code",
    "list_races",
    "get_leaderboard",
    "check_interface_restrictions",
    "list_restricted_interfaces",
    "list_x402_facilitators",
    "list_cp0x_x402_resources",
    "about_cp0x", "list_cp0x_open_source",
}
MARKETING_WORDS = ("best", "exclusive", "promo", "guaranteed", "earn more", "don't miss")


def run(coro):
    return asyncio.run(coro)


def payload(result):
    """Tool results are JSON text in the first content block."""
    assert result.is_error is False
    return json.loads(result.content[0].text)


@pytest.fixture
def server(service):
    from cp0x_mcp.server import build_server

    return build_server(service)


def test_build_server_exposes_exactly_the_read_only_tools(server):
    tools = run(server.list_tools())
    assert {t.name for t in tools} == TOOL_NAMES
    for t in tools:
        assert len(t.name) <= 64
        assert t.title, t.name
        assert t.annotations is not None and t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name
        assert t.description and "Use this when" in t.description, t.name
        assert not any(w in t.description.lower() for w in MARKETING_WORDS), t.name


def test_server_identity(server):
    assert server.name == "cp0x"
    assert server.instructions and "cp0x" in server.instructions


def test_input_schemas_carry_bounds(server):
    tools = {t.name: t for t in run(server.list_tools())}
    top = tools["get_leaderboard"].input_schema["properties"]["top"]
    assert top.get("minimum") == 1 and top.get("maximum") == 100
    limit = tools["list_deals"].input_schema["properties"]["limit"]
    assert limit.get("minimum") == 1 and limit.get("maximum") == 100
    assert "slug" in tools["get_leaderboard"].input_schema["required"]
    assert "venue" in tools["get_referral_code"].input_schema["required"]
    assert "country" in tools["list_restricted_interfaces"].input_schema["required"]
    country = tools["check_interface_restrictions"].input_schema["properties"]["country"]
    assert country.get("maxLength") == 2 or country.get("pattern")


def test_call_get_referral_code_returns_service_payload_with_attribution(server):
    data = payload(run(server.call_tool("get_referral_code", {"venue": "Extended"})))
    assert data["match"]["slug"] == "extended"
    assert data["match"]["code_hint"] == "CP0X"
    assert data["attribution"]["source"] == "cp0x"


def test_call_check_interface_restrictions(server):
    data = payload(run(server.call_tool("check_interface_restrictions", {"protocol": "centrifuge", "country": "au"})))
    assert data["interface"]["id"] == "centrifuge"
    assert data["observed"][0]["blocked"] is False


def test_call_list_deals_with_query_and_limit(server):
    data = payload(run(server.call_tool("list_deals", {"query": "tally", "limit": 1})))
    assert data["count"] == 2 and len(data["deals"]) == 1


def test_invalid_arguments_are_rejected_before_the_service_runs(server):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        run(server.call_tool("get_leaderboard", {"slug": "risex", "top": 0}))
    with pytest.raises(ToolError):
        run(server.call_tool("get_referral_code", {}))


# ---------- ASGI app: health, host allowlist, rate limit ----------

@pytest.fixture
def app(server):
    from cp0x_mcp.server import build_app

    return build_app(server, allowed_hosts=["mcp.cp0x.com", "mcp.cp0x.com:*"], per_ip_per_minute=3, clock=FakeClock())


def get(app, path, host="mcp.cp0x.com"):
    async def _go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}") as client:
            return await client.get(path)

    return run(_go())


def test_health_endpoint(app):
    response = get(app, "/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["server"] == "cp0x"
    assert "version" in body


def test_mcp_route_is_mounted(app):
    assert any(getattr(route, "path", "") in ("/mcp", "/mcp/") for route in app.routes)


def test_disallowed_host_is_refused(app):
    response = get(app, "/health", host="evil.example")
    assert response.status_code == 421


def test_rate_limit_per_caller_ip(app):
    statuses = [get(app, "/health").status_code for _ in range(4)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    response = get(app, "/health")
    assert response.status_code == 429 and response.headers.get("retry-after")


def test_rate_limiter_unit():
    from cp0x_mcp.limits import RateLimiter

    clock = FakeClock()
    limiter = RateLimiter(per_minute=2, clock=clock)
    assert limiter.allow("a") == (True, 0)
    assert limiter.allow("a") == (True, 0)
    allowed, retry_after = limiter.allow("a")
    assert allowed is False and 0 < retry_after <= 60
    assert limiter.allow("b") == (True, 0)  # keys are independent
    clock.advance(61)
    assert limiter.allow("a") == (True, 0)


def test_parse_args_defaults_and_stdio():
    from cp0x_mcp.server import parse_args

    default = parse_args([])
    assert default.transport == "http" and default.host == "127.0.0.1" and default.port == 8000
    stdio = parse_args(["--transport", "stdio"])
    assert stdio.transport == "stdio"
    custom = parse_args(["--host", "0.0.0.0", "--port", "9100", "--allowed-host", "mcp.cp0x.com", "--per-ip-per-minute", "30"])
    assert custom.host == "0.0.0.0" and custom.port == 9100
    assert custom.allowed_host == ["mcp.cp0x.com"] and custom.per_ip_per_minute == 30

"""Contracts added after the Codex reviews of m2 and m3: default host allowlist with ports, shared upstream budget with
Retry-After backoff and negative caching, structured retry hints in results, 429 handling, proxy and docs fixes."""
import asyncio
from pathlib import Path

import httpx
import pytest

from tests.conftest import FakeClock, FakeHTTP

ROOT = Path(__file__).resolve().parent.parent
HOST_A = "https://cp0x.test"
HOST_B = "https://other.test"


def make(budget=3, negative_ttl=30):
    from cp0x_mcp.upstream import Fetcher

    routes = {f"{HOST_A}/u{i}": "facilitators.json" for i in range(10)}
    routes.update({f"{HOST_B}/u{i}": "facilitators.json" for i in range(3)})
    http = FakeHTTP(routes)
    clock = FakeClock()
    return Fetcher(http, clock=clock, budget_per_minute=budget, negative_ttl_s=negative_ttl), http, clock


# ---------- 1. default host allowlist accepts the listening port ----------

def test_parse_args_default_allowlist_includes_port_patterns():
    from cp0x_mcp.server import parse_args

    assert parse_args([]).allowed_host == ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]


def test_default_allowlist_serves_health_on_localhost_with_port(service):
    from cp0x_mcp.server import build_app, build_server, parse_args

    app = build_app(build_server(service), allowed_hosts=parse_args([]).allowed_host, per_ip_per_minute=100, clock=FakeClock())

    async def get(host):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}") as client:
            return (await client.get("/health")).status_code

    assert asyncio.run(get("localhost:8000")) == 200
    assert asyncio.run(get("127.0.0.1:8000")) == 200
    assert asyncio.run(get("evil.example:8000")) == 421


# ---------- 2. shared upstream budget per host ----------

def test_budget_blocks_the_call_beyond_the_per_minute_limit():
    from cp0x_mcp.upstream import UpstreamError

    fetcher, http, clock = make(budget=3)
    for i in range(3):
        fetcher.get(f"{HOST_A}/u{i}", ttl_s=60)
    with pytest.raises(UpstreamError) as err:
        fetcher.get(f"{HOST_A}/u3", ttl_s=60)
    assert len(http.calls) == 3
    assert 1 <= err.value.retry_after_s <= 60
    assert "budget" in str(err.value).lower()
    fetcher.get(f"{HOST_B}/u0", ttl_s=60)  # another host has its own budget
    assert len(http.calls) == 4
    clock.advance(61)
    fetcher.get(f"{HOST_A}/u3", ttl_s=60)
    assert len(http.calls) == 5


def test_budget_exhausted_returns_stale_copy_when_cached():
    fetcher, http, clock = make(budget=2)
    first = fetcher.get(f"{HOST_A}/u0", ttl_s=10)
    fetcher.get(f"{HOST_A}/u1", ttl_s=60)
    clock.advance(11)  # u0 expired, budget window still full
    again = fetcher.get(f"{HOST_A}/u0", ttl_s=10)
    assert again.stale is True and again.data == first.data
    assert len(http.calls) == 2


def test_cache_hits_do_not_consume_the_budget():
    fetcher, http, clock = make(budget=2)
    for _ in range(10):
        fetcher.get(f"{HOST_A}/u0", ttl_s=60)
    fetcher.get(f"{HOST_A}/u1", ttl_s=60)
    assert len(http.calls) == 2


# ---------- 3. Retry-After backoff ----------

def test_throttled_upstream_sets_a_host_backoff():
    from cp0x_mcp.upstream import UpstreamError, UpstreamThrottled

    fetcher, http, clock = make(budget=10)
    original = http.__call__

    def throttling(url):
        http.calls.append(url)
        raise UpstreamThrottled(retry_after_s=30, url=url)

    fetcher._get_json = throttling  # first call is throttled by the upstream
    with pytest.raises(UpstreamError) as err:
        fetcher.get(f"{HOST_A}/u0", ttl_s=60)
    assert err.value.retry_after_s == 30
    fetcher._get_json = original
    with pytest.raises(UpstreamError) as err2:  # same host, still backing off: no call
        fetcher.get(f"{HOST_A}/u1", ttl_s=60)
    assert len(http.calls) == 1 and 1 <= err2.value.retry_after_s <= 30
    fetcher.get(f"{HOST_B}/u0", ttl_s=60)  # other hosts unaffected
    assert len(http.calls) == 2
    clock.advance(31)
    fetcher.get(f"{HOST_A}/u1", ttl_s=60)
    assert len(http.calls) == 3


def test_throttled_upstream_with_cache_returns_stale_copy():
    from cp0x_mcp.upstream import UpstreamThrottled

    fetcher, http, clock = make(budget=10)
    first = fetcher.get(f"{HOST_A}/u0", ttl_s=10)
    clock.advance(11)

    def throttling(url):
        http.calls.append(url)
        raise UpstreamThrottled(retry_after_s=30, url=url)

    fetcher._get_json = throttling
    stale = fetcher.get(f"{HOST_A}/u0", ttl_s=10)
    assert stale.stale is True and stale.data == first.data
    assert len(http.calls) == 2
    stale_again = fetcher.get(f"{HOST_A}/u0", ttl_s=10)  # backing off: served from cache without a call
    assert stale_again.stale is True
    assert len(http.calls) == 2


# ---------- 4. negative cache ----------

def test_failed_lookup_is_not_retried_within_negative_ttl():
    from cp0x_mcp.upstream import UpstreamError

    fetcher, http, clock = make(budget=10, negative_ttl=30)
    http.fail.add(f"{HOST_A}/u0")
    with pytest.raises(UpstreamError):
        fetcher.get(f"{HOST_A}/u0", ttl_s=60)
    with pytest.raises(UpstreamError) as err:
        fetcher.get(f"{HOST_A}/u0", ttl_s=60)
    assert len(http.calls) == 1
    assert 1 <= err.value.retry_after_s <= 30
    fetcher.get(f"{HOST_A}/u1", ttl_s=60)  # only the failed URL is negatively cached
    assert len(http.calls) == 2
    clock.advance(31)
    http.fail.discard(f"{HOST_A}/u0")
    fetcher.get(f"{HOST_A}/u0", ttl_s=60)
    assert len(http.calls) == 3


# ---------- 5. results carry the retry hint, per host ----------

def test_service_result_reports_retry_after(service, http):
    from cp0x_mcp.upstream import UpstreamThrottled

    def throttling(url):
        http.calls.append(url)
        raise UpstreamThrottled(retry_after_s=45, url=url)

    service._fetcher._get_json = throttling
    result = service.list_x402_facilitators()
    assert result["facilitators"] == []
    assert "error" in result and result["retry_after_s"] == 45
    service._fetcher._get_json = http
    healthy = service.list_deals()  # cp0x.com is a different host: not backing off
    assert "error" not in healthy and healthy["count"] == 30
    again = service.list_x402_facilitators()  # x402-api.cp0x.com still backing off, no new call
    assert "error" in again and 1 <= again["retry_after_s"] <= 45
    assert http.calls.count("https://x402-api.cp0x.com/api/free/facilitators") == 1


def test_service_result_retry_after_is_none_for_plain_failures(service, http):
    from cp0x_mcp import sources

    http.fail.add(sources.DEALS_URL)
    result = service.list_deals()
    assert "error" in result and result["retry_after_s"] is None


# ---------- 6. the real HTTP client turns 429 into a throttle signal ----------

def test_get_json_turns_429_into_throttled():
    from cp0x_mcp.server import get_json
    from cp0x_mcp.upstream import UpstreamThrottled

    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/throttled":
            return httpx.Response(429, headers={"Retry-After": "17"})
        if request.url.path == "/throttled-bare":
            return httpx.Response(429)
        if request.url.path == "/missing":
            return httpx.Response(404)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    assert get_json("https://cp0x.test/fine", transport=transport) == {"ok": True}
    assert seen[-1].headers["User-Agent"].startswith("cp0x-mcp/")
    with pytest.raises(UpstreamThrottled) as err:
        get_json("https://cp0x.test/throttled", transport=transport)
    assert err.value.retry_after_s == 17 and err.value.url == "https://cp0x.test/throttled"
    with pytest.raises(UpstreamThrottled) as bare:
        get_json("https://cp0x.test/throttled-bare", transport=transport)
    assert bare.value.retry_after_s == 60
    with pytest.raises(httpx.HTTPStatusError):
        get_json("https://cp0x.test/missing", transport=transport)


# ---------- 7. docs and deployment ----------

def test_dockerfile_declares_trusted_proxies():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FORWARDED_ALLOW_IPS" in text


def test_readme_documents_proxy_ports_and_new_fields():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "FORWARDED_ALLOW_IPS" in text
    assert "--allowed-host localhost:8000" in text
    for field in ("fetched_at", "age_s", "stale_since", "country_match", "scope", "retry_after_s"):
        assert f"`{field}`" in text, field
    assert "45 requests" in text or "45 upstream requests" in text

"""Contracts added after the Codex review of m12: a price counts only when it values a known amount, and a headline built
from stale cached prices says so instead of claiming today's prices."""
from tests.conftest import FakeClock, FakeHTTP, routes_for_sources


def test_a_price_for_an_unknown_amount_does_not_make_a_headline():
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    service = Cp0xService(Fetcher(lambda url: {"paradex": {"usd": 0.05}}, clock=FakeClock()))
    d = service.about_cp0x()["distributed_to_users"]
    assert d["value_now_usd"] is None and d["complete"] is False
    assert d["prices"]["error"] == "unusable price response"
    assert d["summary"].startswith("cp0x has passed about $2.8M at the time of distribution to its users: ")
    dime = [i for i in d["items"] if i["token"] == "DIME"][0]
    assert dime["price_usd"] == 0.05 and dime["value_now_usd"] is None


def test_stale_prices_qualify_the_headline():
    from cp0x_mcp import sources
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    http = FakeHTTP(routes_for_sources())
    clock = FakeClock()
    service = Cp0xService(Fetcher(http, clock=clock, wall=lambda: 1_700_000_000.0))  # 2023-11-14T22:13:20Z
    fresh = service.about_cp0x()["distributed_to_users"]
    assert fresh["prices"]["stale"] is False
    assert fresh["summary"].startswith(f"cp0x has passed about ${fresh['value_now_usd'] / 1e6:.1f}M at today's prices to its users: ")
    clock.advance(2 * 86400)
    http.fail.add(sources.COINGECKO_PRICES_URL)
    stale = service.about_cp0x()["distributed_to_users"]
    assert stale["prices"]["stale"] is True and stale["value_now_usd"] == fresh["value_now_usd"]
    assert stale["summary"].startswith(
        f"cp0x has passed about ${stale['value_now_usd'] / 1e6:.1f}M at cached prices from 2023-11-14 to its users: ")
    assert "today" not in stale["summary"]

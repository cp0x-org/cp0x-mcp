"""m20: leaderboard freshness reaches enriched responses; record conditions pass through."""
from datetime import date

import pytest

from tests.conftest import load

TODAY = date(2026, 10, 25)


def _service(http, clock):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    return Cp0xService(Fetcher(http, clock=clock, wall=lambda: 1_700_000_000.0 + clock()),
                       benefits=load("benefits.json"), today=lambda: TODAY)


@pytest.fixture
def stale_board(http, clock):
    """Deals refresh fine, the RISEx leaderboard fails after its TTL and is served from cache."""
    from cp0x_mcp import sources

    service = _service(http, clock)
    first = service.get_deal("risex")
    assert first["race_cases"]["freshness"]["stale"] is False and first["stale"] is False
    clock.advance(61)
    http.fail.add(sources.race_url("risex", "leaderboard"))
    return service


def test_get_deal_reports_a_stale_leaderboard(stale_board):
    result = stale_board.get_deal("risex")
    assert result["race_cases"] is not None
    freshness = result["race_cases"]["freshness"]
    assert freshness["stale"] is True and freshness["stale_since"] and freshness["fetched_at"]
    assert result["stale"] is True


def test_compare_reports_a_stale_leaderboard(stale_board):
    result = stale_board.compare_referral_benefits(category="perps")
    risex = next(d for d in result["deals"] if d["slug"] == "risex")
    assert risex["race_cases"]["freshness"]["stale"] is True
    assert result["stale"] is True


def test_fresh_leaderboard_freshness_fields(http, clock):
    rc = _service(http, clock).get_deal("risex")["race_cases"]
    assert set(rc["freshness"]) == {"stale", "fetched_at", "age_s", "stale_since"}
    assert rc["freshness"]["stale"] is False and rc["freshness"]["stale_since"] is None


def test_record_conditions_pass_through_without_quotes(http, clock):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    record = dict(load("benefits.json")["venues"]["risex"])
    record["conditions"] = [{"text": "Enrollment closed on 2026-03-18.", "source_url": "https://cp0x.com/deals/risex"}]
    service = Cp0xService(Fetcher(http, clock=clock), benefits={"version": 1, "venues": {"risex": record}}, today=lambda: TODAY)
    assert service.get_deal("risex")["benefit"]["conditions"] == record["conditions"]


def test_bundled_conditions_shape():
    from cp0x_mcp.benefits import load_benefits

    for slug, rec in load_benefits()["venues"].items():
        for condition in rec.get("conditions", []):
            assert set(condition) == {"text", "source_url"}, slug
            assert condition["text"].strip() and condition["source_url"].startswith("https://"), slug
        if "fees_note" in rec:
            assert rec["fees_note"].strip() and rec.get("taker_fee_bps") is not None, slug

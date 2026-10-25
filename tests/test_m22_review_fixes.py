"""m22: one freshness rule for enriched responses; unknown original fee sizes give no dollar advantage."""
from datetime import date

from tests.conftest import load

TODAY = date(2026, 10, 25)


def _service(http, clock, benefits=None):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    return Cp0xService(Fetcher(http, clock=clock, wall=lambda: 1_700_000_000.0 + clock()),
                       benefits=benefits or load("benefits.json"), today=lambda: TODAY)


def _stale_board_service(http, clock):
    from cp0x_mcp import sources

    service = _service(http, clock)
    service.get_deal("risex")
    clock.advance(61)
    http.fail.add(sources.race_url("risex", "leaderboard"))
    return service


def _assert_merged(result, freshness):
    assert freshness["stale"] is True
    assert result["stale"] is True
    assert result["fetched_at"] == freshness["fetched_at"]  # the oldest response
    assert result["age_s"] == freshness["age_s"] and result["age_s"] >= 61
    assert result["stale_since"] == freshness["stale_since"] is not None


def test_get_deal_takes_the_oldest_freshness(http, clock):
    result = _stale_board_service(http, clock).get_deal("risex")
    _assert_merged(result, result["race_cases"]["freshness"])


def test_compare_takes_the_oldest_freshness(http, clock):
    result = _stale_board_service(http, clock).compare_referral_benefits(category="perps")
    risex = next(d for d in result["deals"] if d["slug"] == "risex")
    _assert_merged(result, risex["race_cases"]["freshness"])


def test_fresh_responses_keep_their_own_freshness(http, clock):
    result = _service(http, clock).get_deal("risex")
    assert result["stale"] is False and result["stale_since"] is None


def test_unknown_original_fee_size_gives_no_dollar_advantage(http, clock):
    venues = {"ondo_perps": {
        "category": "perps",
        "cp0x": [{"kind": "fee_discount", "value": 5, "unit": "%", "applies_to": "trading_fees", "quote": "5%",
                  "source_url": "https://cp0x.com/deals/ondo_perps"}],
        "original": {"status": "found", "items": [{"kind": "fee_discount", "value": None, "unit": None, "applies_to": "trading_fees",
                                                   "quote": "referees get a discount", "source_url": "https://docs.example.org/r"}]},
        "taker_fee_bps": 4.0, "fees_source_url": "https://docs.example.org/fees", "checked_at": "2026-10-20"}}
    per = _service(http, clock, {"version": 1, "venues": venues}).get_deal("ondo_perps")["benefit"]["per_10k_usd_traded"]
    assert per["saving_usd"] == 0.2
    assert per["saving_vs_original_usd"] is None

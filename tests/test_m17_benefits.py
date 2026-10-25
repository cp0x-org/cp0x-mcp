"""Referral benefit of the cp0x code against the venue's own offer, race-based volume cases and the comparison tool.

Fixture numbers are synthetic (tests/fixtures/benefits.json, leaderboard_ondo_race.json).
"""
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from tests.conftest import load

TODAY = date(2026, 10, 25)
ROOT = Path(__file__).resolve().parents[1]


def _service(http, clock, benefits=None):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    return Cp0xService(Fetcher(http, clock=clock), benefits=benefits or load("benefits.json"), today=lambda: TODAY)


@pytest.fixture
def svc(http, clock):
    return _service(http, clock)


def _benefit(svc, slug):
    return svc.get_deal(slug)["benefit"]


# --- data file ----------------------------------------------------------------------------------------------------


def test_bundled_benefits_file_loads():
    from cp0x_mcp.benefits import load_benefits

    data = load_benefits()
    assert isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("venues"), dict)
    assert (ROOT / "cp0x_mcp" / "data" / "benefits.json").is_file()


def test_default_service_still_constructs_without_benefit_arguments(service):
    assert service.list_deals(limit=1)["deals"]


# --- benefit field ------------------------------------------------------------------------------------------------


def test_fee_discount_against_a_found_original_offer(svc):
    b = _benefit(svc, "ondo_perps")
    assert b["category"] == "perps"
    assert b["cp0x"] == [{"kind": "fee_discount", "value": 5, "unit": "%", "applies_to": "trading_fees",
                          "source_url": "https://cp0x.com/deals/ondo_perps"}]
    assert b["original"]["status"] == "found"
    assert b["delta"] == [{"kind": "fee_discount", "unit": "%", "cp0x": 5, "original": 3, "better": True, "worse": False}]
    per = b["per_10k_usd_traded"]
    assert per["taker_fee_bps"] == 4.0 and per["fees_source_url"] == "https://docs.example.org/fees"
    assert per["saving_usd"] == pytest.approx(0.2)  # $10,000 x 4 bps x 5 %
    assert per["saving_vs_original_usd"] == pytest.approx(0.08)  # $10,000 x 4 bps x (5 - 3) %
    assert b["checked_at"] == "2026-10-20" and b["stale"] is False


def test_quotes_stay_in_the_data_file_not_in_responses(svc):
    text = json.dumps(svc.compare_referral_benefits()) + json.dumps(svc.get_deal("ondo_perps"))
    assert '"quote"' not in text


def test_original_none_counts_as_zero_and_items_without_value_are_skipped(svc):
    b = _benefit(svc, "risex")
    assert b["delta"] == [{"kind": "points_boost", "unit": "%", "cp0x": 20, "original": 0, "better": True, "worse": False}]
    assert b["per_10k_usd_traded"] is None  # no fee benefit


def test_equal_and_worse_offers_are_reported_as_they_are(svc):
    equal = _benefit(svc, "hyperliquid")
    assert equal["delta"] == [{"kind": "fee_discount", "unit": "%", "cp0x": 4, "original": 4, "better": False, "worse": False}]
    assert equal["per_10k_usd_traded"]["saving_usd"] == pytest.approx(0.18)
    assert equal["per_10k_usd_traded"]["saving_vs_original_usd"] == pytest.approx(0.0)
    worse = _benefit(svc, "vooi")
    assert worse["delta"] == [{"kind": "points_boost", "unit": "%", "cp0x": 15, "original": 20, "better": False, "worse": True}]


def test_no_delta_without_a_found_original_or_for_loyalty(svc):
    assert _benefit(svc, "lighter")["delta"] is None  # original not_found
    assert _benefit(svc, "mellow")["delta"] is None  # loyalty only


def test_fee_benefit_without_a_known_fee_has_no_dollar_figure(svc):
    b = _benefit(svc, "preddy")
    assert b["delta"][0]["better"] is True
    assert b["per_10k_usd_traded"] is None


def test_stale_after_thirty_days(svc):
    assert _benefit(svc, "nansen")["stale"] is True
    assert _benefit(svc, "ondo_perps")["stale"] is False


def test_deal_without_a_record_has_null_benefit(svc):
    assert _benefit(svc, "extended") is None


def test_benefit_sits_next_to_the_deal_and_leaves_the_deal_objects_unchanged(svc):
    from tests.conftest import load as _load

    result = svc.get_deal("ondo_perps")
    assert result["benefit"]["delta"][0]["better"] is True
    assert result["deal"] == next(d for d in _load("deals.json")["deals"] if d["slug"] == "ondo_perps")
    match = svc.get_referral_code("ondo")
    assert match["benefit"]["category"] == "perps" and "benefit" not in match["match"]
    assert all("benefit" not in d and "race_cases" not in d for d in svc.list_deals()["deals"])


def test_list_deals_does_not_fetch_leaderboards(svc, http):
    svc.list_deals()
    assert all("/races/" not in url for url in http.calls)


# --- race cases ---------------------------------------------------------------------------------------------------


def test_race_cases_by_volume_with_points_prizes(svc):
    rc = svc.get_deal("risex")["race_cases"]
    board = load("leaderboard_risex.json")
    entries = board["entries"]
    last_paid = max(e["rank"] for e in entries if e.get("prize"))
    assert rc["race"]["code"] == "leaderboard" and rc["race"]["ranked_by"] == "volume"
    assert rc["race"]["prize_currency"] == "points" and rc["race"]["prize_pool"] == 12000
    assert rc["race"]["leaderboard_updated"] == board["race"]["last_update"]
    cases = {c["case"]: c for c in rc["cases"]}
    assert [c["case"] for c in rc["cases"]] == ["first", "top10", "last_paid"]
    assert cases["first"]["rank"] == 1 and cases["first"]["volume"] == entries[0]["volume"]
    assert cases["first"]["race_prize"] == entries[0]["prize"]
    assert cases["top10"]["rank"] == 10
    assert cases["last_paid"]["rank"] == last_paid
    for c in rc["cases"]:
        assert c["base_saving_usd"] is None and c["total_usd"] is None  # points boost: no dollars
    assert rc["base_benefits"] and all(isinstance(s, str) for s in rc["base_benefits"])
    assert any("20" in s and "points" in s for s in rc["base_benefits"])
    assert rc["note"]


def test_race_cases_by_fees_with_usd_prizes(http, clock):
    from cp0x_mcp import sources

    http.routes[sources.DEALS_URL] = "deals_with_fee_race.json"
    http.routes[sources.race_url("ondo_perps", "ondo_race")] = "leaderboard_ondo_race.json"
    rc = _service(http, clock).get_deal("ondo_perps")["race_cases"]
    assert rc["race"]["ranked_by"] == "fees" and rc["race"]["prize_currency"] == "USD"
    cases = {c["case"]: c for c in rc["cases"]}
    assert (cases["first"]["rank"], cases["first"]["fees"]) == (1, 1000)
    assert cases["first"]["base_saving_usd"] == pytest.approx(1000 * 5 / 95)  # fees paid are net of a 5 % discount
    assert cases["first"]["total_usd"] == pytest.approx(500 + 1000 * 5 / 95)
    assert (cases["top10"]["rank"], cases["top10"]["race_prize"]) == (10, 0)
    assert cases["top10"]["total_usd"] == pytest.approx(100 * 5 / 95)
    assert (cases["last_paid"]["rank"], cases["last_paid"]["race_prize"]) == (8, 10)
    assert cases["last_paid"]["total_usd"] == pytest.approx(10 + 150 * 5 / 95)


def test_no_race_cases_without_an_active_race_or_a_record(svc):
    assert svc.get_deal("ondo_perps")["race_cases"] is None  # no races in the base fixture
    assert svc.get_deal("extended")["race_cases"] is None  # no benefit record


def test_a_failing_leaderboard_does_not_break_get_deal(http, clock):
    from cp0x_mcp import sources

    http.fail.add(sources.race_url("risex", "leaderboard"))
    result = _service(http, clock).get_deal("risex")
    assert result["benefit"] is not None and result["race_cases"] is None


# --- comparison tool ----------------------------------------------------------------------------------------------


def test_compare_order_and_groups(svc):
    result = svc.compare_referral_benefits()
    slugs = [d["slug"] for d in result["deals"]]
    deals_order = [d["slug"] for d in load("deals.json")["deals"]]
    assert slugs[:4] == ["ondo_perps", "preddy", "risex", "nansen"]  # better: dollars first, then size of the gap
    assert slugs[4:6] == ["hyperliquid", "vooi"]  # compared, not better (API order)
    rest = slugs[6:]
    assert rest == [s for s in deals_order if s in set(rest)]  # no comparison: API order, nothing hidden
    assert set(slugs) == set(deals_order)
    first = result["deals"][0]
    for key in ("slug", "title", "link", "benefit"):
        assert key in first
    assert result["note"]


def test_compare_by_category(svc):
    result = svc.compare_referral_benefits(category="perps")
    assert [d["slug"] for d in result["deals"]] == ["ondo_perps", "risex", "hyperliquid", "lighter"]
    assert result["category"] == "perps"


def test_compare_includes_race_cases_for_records_with_an_active_race(svc):
    risex = next(d for d in svc.compare_referral_benefits(category="perps")["deals"] if d["slug"] == "risex")
    assert risex["race_cases"]["race"]["code"] == "leaderboard"


def test_compare_tool_is_registered_without_country_or_volume_inputs(service):
    from cp0x_mcp.server import build_server

    tools = {t.name: t for t in asyncio.run(build_server(service).list_tools())}
    tool = tools["compare_referral_benefits"]
    assert set(tool.input_schema["properties"]) == {"category"}
    assert tool.title and tool.annotations.title == tool.title and tool.annotations.read_only_hint is True
    text = tool.description.lower()
    assert "use this when" in text
    assert not any(word in text for word in ("best", "always", "prefer", "country", "volume per month"))


def test_server_instructions_count_twelve_tools(service):
    from cp0x_mcp.server import build_server

    assert "Twelve read-only tools" in build_server(service).instructions


def test_readme_lists_the_comparison_tool():
    assert "`compare_referral_benefits`" in (ROOT / "README.md").read_text(encoding="utf-8")


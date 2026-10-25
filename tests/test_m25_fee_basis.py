"""m25: on a fee-ranked race a rebate is a share of fees paid, a discount is recovered from net fees paid."""
from datetime import date

import pytest

from tests.conftest import load


def _rc(http, clock, kind):
    from cp0x_mcp import sources
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    http.routes[sources.DEALS_URL] = "deals_with_fee_race.json"
    http.routes[sources.race_url("ondo_perps", "ondo_race")] = "leaderboard_ondo_race.json"
    record = dict(load("benefits.json")["venues"]["ondo_perps"])
    record["cp0x"] = [dict(record["cp0x"][0], kind=kind)]
    service = Cp0xService(Fetcher(http, clock=clock), benefits={"version": 1, "venues": {"ondo_perps": record}},
                          today=lambda: date(2026, 10, 25))
    return {c["case"]: c for c in service.get_deal("ondo_perps")["race_cases"]["cases"]}


def test_rebate_is_a_share_of_fees_paid(http, clock):
    cases = _rc(http, clock, "fee_rebate")
    assert cases["first"]["base_saving_usd"] == pytest.approx(50.0)
    assert cases["last_paid"]["total_usd"] == pytest.approx(17.5)


def test_discount_is_recovered_from_net_fees_paid(http, clock):
    cases = _rc(http, clock, "fee_discount")
    assert cases["first"]["base_saving_usd"] == pytest.approx(1000 / 0.95 - 1000)
    assert cases["top10"]["base_saving_usd"] == pytest.approx(100 / 0.95 - 100)


def test_bundled_fee_percentages_are_below_one_hundred():
    from cp0x_mcp.benefits import load_benefits

    for slug, rec in load_benefits()["venues"].items():
        for item in rec["cp0x"] + rec["original"].get("items", []):
            if item["kind"] in {"fee_discount", "fee_rebate"} and item.get("unit") == "%" and item.get("value") is not None:
                assert 0 < item["value"] < 100, slug

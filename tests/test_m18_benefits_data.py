"""m18: kinds only the venue's own offer has, unsized original items, race end date, and invariants of the bundled data."""
import math
from datetime import date

from tests.conftest import load

TODAY = date(2026, 10, 25)
CATEGORIES = {
    "perps", "exchange", "prediction", "staking", "lending", "analytics", "dex", "depin", "governance", "payments", "wallet", "defi",
}
STATUSES = {"found", "none", "not_found", "not_applicable"}


def _service(http, clock, venues):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    return Cp0xService(Fetcher(http, clock=clock), benefits={"version": 1, "venues": venues}, today=lambda: TODAY)


def _item(kind, value, unit="%", applies_to="points", url="https://docs.example.org/referral"):
    return {"kind": kind, "value": value, "unit": unit, "applies_to": applies_to, "quote": f"{kind} {value}", "source_url": url}


def _record(cp0x, original, taker=None):
    return {"category": "perps", "cp0x": cp0x, "original": original, "taker_fee_bps": taker,
            "fees_source_url": "https://docs.example.org/fees" if taker is not None else None, "checked_at": "2026-10-20"}


def test_a_kind_only_the_original_offer_has_is_not_stated_for_cp0x(http, clock):
    venues = {"extended": _record(
        [_item("points_boost", 20, url="https://cp0x.com/deals/extended")],
        {"status": "found", "items": [_item("fee_discount", 10, applies_to="trading_fees")]},
        taker=2.5,
    )}
    benefit = _service(http, clock, venues).get_deal("extended")["benefit"]
    assert benefit["delta"] == [
        {"kind": "points_boost", "unit": "%", "cp0x": 20, "original": 0, "better": True, "worse": False},
        {"kind": "fee_discount", "unit": "%", "cp0x": None, "original": 10, "better": False, "worse": False,
         "note": "not stated for the cp0x code"},
    ]
    assert benefit["per_10k_usd_traded"] is None  # the cp0x side has no fee benefit


def test_an_unsized_original_item_of_the_same_kind_is_unknown_not_zero(http, clock):
    venues = {"fluence": _record(
        [_item("points_boost", 30, url="https://cp0x.com/deals/fluence")],
        {"status": "found", "items": [_item("points_boost", None, unit=None)]},
    )}
    benefit = _service(http, clock, venues).get_deal("fluence")["benefit"]
    assert benefit["delta"] == [
        {"kind": "points_boost", "unit": "%", "cp0x": 30, "original": None, "better": False, "worse": False,
         "note": "original size not stated"},
    ]


def test_a_sized_original_item_wins_over_an_unsized_one_of_the_same_kind(http, clock):
    venues = {"nansen": _record(
        [_item("fee_discount", 15, applies_to="subscriptions", url="https://cp0x.com/deals/nansen")],
        {"status": "found", "items": [_item("fee_discount", 10, applies_to="subscriptions"), _item("fee_discount", None, unit="bps")]},
    )}
    benefit = _service(http, clock, venues).get_deal("nansen")["benefit"]
    assert benefit["delta"] == [
        {"kind": "fee_discount", "unit": "%", "cp0x": 15, "original": 10, "better": True, "worse": False},
    ]


def test_race_carries_its_end_date(http, clock):
    from cp0x_mcp import sources

    http.routes[sources.DEALS_URL] = "deals_with_fee_race.json"
    http.routes[sources.race_url("ondo_perps", "ondo_race")] = "leaderboard_ondo_race.json"
    venues = {"ondo_perps": _record([_item("fee_discount", 5, url="https://cp0x.com/deals/ondo_perps")],
                                    {"status": "found", "items": [_item("fee_discount", 3)]}, taker=4.0)}
    race = _service(http, clock, venues).get_deal("ondo_perps")["race_cases"]["race"]
    assert race["ends_at"] == "2026-11-30T00:00:00Z"


# --- bundled data -------------------------------------------------------------------------------------------------


def _bundled():
    from cp0x_mcp.benefits import load_benefits

    return load_benefits()


def test_bundled_data_covers_the_researched_deals():
    venues = _bundled()["venues"]
    deal_slugs = {d["slug"] for d in load("deals.json")["deals"]}
    assert set(venues) <= deal_slugs
    assert len(venues) >= 28  # 20 researched deals and the cp0x loyalty deals; legion has no public offer


def test_bundled_records_have_provenance_and_valid_fields():
    for slug, rec in _bundled()["venues"].items():
        assert rec["category"] in CATEGORIES, slug
        date.fromisoformat(rec["checked_at"])
        assert rec["cp0x"], slug
        for item in rec["cp0x"]:
            assert item["source_url"].startswith("https://cp0x.com/"), slug
            assert item.get("quote", "").strip(), slug
        original = rec["original"]
        assert original["status"] in STATUSES, slug
        for item in original.get("items", []):
            assert item["source_url"].startswith("https://") and "cp0x.com" not in item["source_url"], slug
            assert item.get("quote", "").strip(), slug
        if original["status"] in {"found", "none"}:
            assert original.get("items"), slug
        fee = rec.get("taker_fee_bps")
        if fee is not None:
            assert isinstance(fee, (int, float)) and math.isfinite(fee) and 0 <= fee <= 100, slug
            assert rec.get("fees_source_url", "").startswith("https://"), slug


def test_bundled_cp0x_items_do_not_double_count_a_kind():
    for slug, rec in _bundled()["venues"].items():
        sized = [(i["kind"], i.get("unit")) for i in rec["cp0x"]
                 if i["kind"] not in {"loyalty", "other"} and isinstance(i.get("value"), (int, float))]
        assert len(sized) == len(set(sized)), slug


def test_bundled_data_through_the_service(http, clock):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    from cp0x_mcp import sources

    http.fail.update({sources.race_url("extended", "extended_race"), sources.race_url("variational_omni", "variational_race_october")})
    service = Cp0xService(Fetcher(http, clock=clock), today=lambda: TODAY)
    result = service.compare_referral_benefits()
    assert {d["slug"] for d in result["deals"]} == {d["slug"] for d in load("deals.json")["deals"]}
    for deal in result["deals"]:
        benefit = deal["benefit"]
        if benefit and benefit["delta"]:
            for pair in benefit["delta"]:
                if pair["better"]:
                    assert isinstance(pair["cp0x"], (int, float)) and isinstance(pair["original"], (int, float))

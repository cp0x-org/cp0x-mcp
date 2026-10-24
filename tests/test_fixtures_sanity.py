"""Positive control: the fixtures are intact. Passes on the RED base; does not import the package."""
from tests.conftest import load


def test_fixture_counts():
    assert len(load("deals.json")["deals"]) == 30
    assert len(load("leaderboard_risex.json")["entries"]) == 155
    assert len(load("monitor_interfaces.json")["interfaces"]) == 8
    assert len(load("monitor_observations.json")["observations"]) == 7
    assert len(load("facilitators.json")) == 9
    assert len(load("cp0x_resources.json")["items"]) == 17


def test_fixture_values_used_by_contracts():
    interfaces = {i["id"]: i for i in load("monitor_interfaces.json")["interfaces"]}
    assert interfaces["uniswap"]["geo_site"]["countries"] == ["UA"]
    assert interfaces["lido"]["geo_feature"]["countries"] == ["US"]
    assert "BR" in interfaces["polymarket"]["geo_site"]["countries"]
    assert load("monitor_interfaces.json")["meta"]["generated"] == "2026-10-11"
    deals = {d["slug"]: d for d in load("deals.json")["deals"]}
    assert {"tally_arb", "tally_op", "nansen", "extended", "risex"} <= set(deals)
    assert "code" not in deals["nansen"] and deals["nansen"]["link"] == "https://nsn.ai/cp0xbased"
    assert deals["ondo_perps"]["code"] == "JL59WM" and deals["lighter"]["code"] == ""
    assert deals["extended"]["link"] == "https://app.extended.exchange/join/CP0X"

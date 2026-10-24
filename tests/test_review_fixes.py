"""Contracts added after the Codex review of m1 (4 × P2): identifier validation, close-only and regional restrictions,
all status layers in declarations (kyc), freshness timing on results."""
import pytest

from tests.conftest import FakeClock, FakeHTTP, routes_for_sources


class FakeWall:
    def __init__(self, start: float = 1_700_000_000.0):  # 2023-11-14T22:13:20Z
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def timed():
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    http = FakeHTTP(routes_for_sources())
    clock, wall = FakeClock(), FakeWall()
    return Cp0xService(Fetcher(http, clock=clock, wall=wall)), http, clock, wall


# ---------- 1. identifiers never reach the URL unvalidated ----------

@pytest.mark.parametrize("bad", ["leaderboard#one", "risex/..", "", "A B", "x" * 65, "ünïcode"])
def test_race_url_rejects_unsafe_identifiers(bad):
    from cp0x_mcp import sources

    with pytest.raises(ValueError):
        sources.race_url("risex", bad)
    with pytest.raises(ValueError):
        sources.race_url(bad, "leaderboard")


def test_race_url_accepts_catalog_identifiers():
    from cp0x_mcp import sources

    assert sources.race_url("extended", "extended_race_january").endswith("/deals/extended/races/extended_race_january")
    assert sources.race_url("tally_arb", "leaderboard").endswith("/deals/tally_arb/races/leaderboard")


def test_get_leaderboard_with_unsafe_identifier_is_an_error_without_fetching(service, http):
    result = service.get_leaderboard("risex", "leaderboard#one")
    assert result["entries"] == [] and "error" in result
    assert http.calls == []
    result = service.get_leaderboard("risex/../x", "leaderboard")
    assert result["entries"] == [] and "error" in result
    assert http.calls == []


def test_country_codes_are_validated_in_the_service(service):
    for bad in ("B R", "BRA", "1A", ""):
        assert "error" in service.check_interface_restrictions("aave", country=bad)
        assert "error" in service.list_restricted_interfaces(bad)
        assert service.list_restricted_interfaces(bad)["interfaces"] == []


# ---------- 2. close-only and regional restrictions ----------

def test_list_restricted_interfaces_close_only_and_regional(service):
    th = {i["id"]: i for i in service.list_restricted_interfaces("th")["interfaces"]}
    assert "polymarket" in th
    assert th["polymarket"]["declared_layers"] == []
    assert th["polymarket"]["close_only_layers"] == ["geo_site"]
    assert th["polymarket"]["regions"] == []
    assert th["polymarket"]["scope"] == "close_only"

    ca = {i["id"]: i for i in service.list_restricted_interfaces("CA")["interfaces"]}
    assert "hyperliquid" in ca
    assert ca["hyperliquid"]["declared_layers"] == []
    assert ca["hyperliquid"]["regions"] == ["CA-ON"]
    assert ca["hyperliquid"]["scope"] == "regional"

    us = {i["id"]: i for i in service.list_restricted_interfaces("US")["interfaces"]}
    assert us["hyperliquid"]["declared_layers"] == ["geo_site"]
    assert us["hyperliquid"]["scope"] == "national"
    assert us["polymarket"]["scope"] == "national"
    for item in us.values():
        assert {"id", "name", "url", "declared_layers", "declared_status", "close_only_layers", "regions", "observed_block", "scope"} <= set(item)


def test_check_interface_restrictions_reports_country_match(service):
    ca = service.check_interface_restrictions("hyperliquid", country="ca")
    assert ca["country_match"] == {"national": False, "close_only": False, "regions": ["CA-ON"], "status": "yes"}
    th = service.check_interface_restrictions("polymarket", country="TH")
    assert th["country_match"] == {"national": False, "close_only": True, "regions": [], "status": "yes"}
    br = service.check_interface_restrictions("polymarket", country="BR")
    assert br["country_match"] == {"national": True, "close_only": False, "regions": [], "status": "yes"}
    assert service.check_interface_restrictions("aave")["country_match"] is None


# ---------- 3. every status layer is declared, kyc included ----------

def test_declared_includes_kyc_and_any_status_layer(service):
    superstate = service.check_interface_restrictions("superstate")["declared"]
    assert superstate["kyc"]["s"] == "yes" and superstate["kyc"]["layer"] == "contract"
    aave = service.check_interface_restrictions("aave")["declared"]
    assert aave["kyc"] is None
    assert {"geo_site", "geo_feature", "screening", "vpn", "asset_filter", "tos", "kyc"} <= set(aave)


# ---------- 4. freshness timing ----------

def test_fresh_results_carry_fetched_at_and_age(timed):
    service, http, clock, wall = timed
    result = service.list_deals()
    assert result["stale"] is False
    assert result["fetched_at"] == "2023-11-14T22:13:20Z"
    assert result["age_s"] == 0
    assert result.get("stale_since") is None
    clock.advance(30)
    wall.advance(30)
    again = service.list_deals()
    assert again["fetched_at"] == "2023-11-14T22:13:20Z" and again["age_s"] == 30


def test_stale_results_carry_stale_since_and_age(timed):
    from cp0x_mcp import sources

    service, http, clock, wall = timed
    service.list_deals()
    clock.advance(sources.TTL_DEALS_S + 1)
    wall.advance(sources.TTL_DEALS_S + 1)
    http.fail.add(sources.DEALS_URL)
    stale = service.list_deals()
    assert stale["stale"] is True
    assert stale["age_s"] == sources.TTL_DEALS_S + 1
    assert stale["fetched_at"] == "2023-11-14T22:13:20Z"
    assert stale["stale_since"] == "2023-11-14T22:14:20Z"  # fetched_at + TTL


def test_multi_source_freshness_uses_the_oldest_source(timed):
    from cp0x_mcp import sources

    service, http, clock, wall = timed
    service.list_x402_facilitators()  # warms only the facilitators cache
    clock.advance(10)
    wall.advance(10)
    service.check_interface_restrictions("aave")  # warms the two monitor sources now
    clock.advance(5)
    wall.advance(5)
    result = service.check_interface_restrictions("aave")
    assert result["age_s"] == 5 and result["fetched_at"] == "2023-11-14T22:13:30Z"
    http.fail.add(sources.MONITOR_INTERFACES_URL)
    clock.advance(sources.TTL_MONITOR_S)
    wall.advance(sources.TTL_MONITOR_S)
    stale = service.check_interface_restrictions("aave")
    assert stale["stale"] is True
    assert stale["age_s"] == 5 + sources.TTL_MONITOR_S
    assert stale["stale_since"] == "2023-11-14T22:23:30Z"  # oldest fetched_at + its TTL


def test_fetched_records_wall_time():
    from cp0x_mcp.upstream import Fetcher

    http = FakeHTTP({"https://example.test/a": "facilitators.json"})
    fetched = Fetcher(http, clock=FakeClock(), wall=FakeWall()).get("https://example.test/a", ttl_s=60)
    assert fetched.fetched_wall == 1_700_000_000.0

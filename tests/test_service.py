"""Contract of cp0x_mcp.service.Cp0xService: one method per MCP tool, plain dict results, attribution everywhere."""

from tests.conftest import load


def assert_attribution(result, url_prefix="https://"):
    attribution = result["attribution"]
    assert attribution["source"] == "cp0x"
    assert attribution["url"].startswith(url_prefix)


# ---------- sources ----------

def test_source_urls_are_pinned():
    from cp0x_mcp import sources

    assert sources.DEALS_URL == "https://cp0x.com/api/v1/deals"
    assert sources.race_url("risex", "leaderboard") == "https://cp0x.com/api/v1/deals/risex/races/leaderboard"
    assert sources.MONITOR_INTERFACES_URL == (
        "https://raw.githubusercontent.com/cp0x-org/pi-restricted-interfaces/main/monitor/current/catalog/interfaces.json"
    )
    assert sources.MONITOR_OBSERVATIONS_URL == (
        "https://raw.githubusercontent.com/cp0x-org/pi-restricted-interfaces/main/monitor/current/catalog/observations.json"
    )
    assert sources.FACILITATORS_URL == "https://x402-api.cp0x.com/api/free/facilitators"
    assert sources.RESOURCES_URL == "https://x402-api.cp0x.com/api/free/cp0x-resources"
    assert sources.TTL_DEALS_S == 60 and sources.TTL_RACES_S == 60
    assert sources.TTL_MONITOR_S == 600 and sources.TTL_X402_S == 300


# ---------- deals ----------

def test_list_deals_returns_all_active_deals_with_compact_fields(service):
    result = service.list_deals()
    fixture = load("deals.json")["deals"]
    assert result["count"] == len(fixture) == 30
    assert [d["slug"] for d in result["deals"]] == [d["slug"] for d in fixture]
    nansen = next(d for d in result["deals"] if d["slug"] == "nansen")
    source = next(d for d in fixture if d["slug"] == "nansen")
    assert set(nansen) == {"slug", "title", "bonus", "code", "code_hint", "link", "page_url", "races"}
    assert nansen["code"] is None and nansen["code_hint"] is None  # no code field upstream, short link carries none
    assert nansen["link"] == source["link"]
    assert "description" not in nansen
    assert_attribution(result, "https://cp0x.com/")


def test_code_is_upstream_code_or_none_and_code_hint_is_parsed_from_link(service):
    deals = {d["slug"]: d for d in service.list_deals()["deals"]}
    assert deals["ondo_perps"]["code"] == "JL59WM" and deals["ondo_perps"]["code_hint"] == "JL59WM"
    assert deals["lighter"]["code"] is None  # upstream sends an empty string: that is "no code", not ""
    expected_hints = {
        "lighter": "CP0XCOOL",  # ?referral=
        "variational_omni": "OMNICP0X",  # ?ref=
        "extended": "CP0X",  # /join/
        "risex": "cp0xbest",  # /invite/
        "paradex": "cp0x1",  # /r/
        "backpack": "cp0x",  # /refer/
        "vooi": "cp0xcool",  # /i/
        "polymarket_perps": "cp0x",  # ?via=
        "nansen": None,  # https://nsn.ai/cp0xbased is a short link, not a code
        "mellow": None,  # vault page without a referral parameter
    }
    assert {slug: deals[slug]["code_hint"] for slug in expected_hints} == expected_hints


def test_list_deals_query_filters_by_title_or_slug_case_insensitive(service):
    result = service.list_deals(query="TALLY")
    assert sorted(d["slug"] for d in result["deals"]) == ["tally_arb", "tally_op"]
    assert result["count"] == 2


def test_list_deals_limit(service):
    result = service.list_deals(limit=5)
    assert len(result["deals"]) == 5
    assert result["count"] == 30  # count = total matching, independent of limit


def test_get_deal_returns_full_api_object(service):
    result = service.get_deal("extended")
    source = next(d for d in load("deals.json")["deals"] if d["slug"] == "extended")
    assert result["deal"] == source
    assert_attribution(result, "https://cp0x.com/deals/extended")


def test_get_deal_unknown_slug_is_an_error_with_known_slugs(service):
    result = service.get_deal("no-such-deal")
    assert result["deal"] is None
    assert "error" in result
    assert "extended" in result["known_slugs"]


def test_get_referral_code_single_match(service):
    result = service.get_referral_code("Extended")
    source = next(d for d in load("deals.json")["deals"] if d["slug"] == "extended")
    assert result["match"]["slug"] == "extended"
    assert result["match"]["code"] is None and result["match"]["code_hint"] == "CP0X"
    assert result["match"]["link"] == source["link"]
    assert result["match"]["bonus"] == source["bonus"]
    assert result["match"]["page_url"] == source["page_url"]
    assert result["candidates"] == []
    assert_attribution(result, source["page_url"])


def test_get_referral_code_ambiguous_returns_candidates_not_a_guess(service):
    result = service.get_referral_code("tally")
    assert result["match"] is None
    assert sorted(c["slug"] for c in result["candidates"]) == ["tally_arb", "tally_op"]


def test_get_referral_code_no_match(service):
    result = service.get_referral_code("definitely-not-a-venue")
    assert result["match"] is None and result["candidates"] == []
    assert "error" in result


# ---------- races ----------

def test_list_races_flattens_races_of_all_deals(service):
    fixture = load("deals.json")["deals"]
    expected = [(d["slug"], r["code"]) for d in fixture for r in d.get("races", [])]
    result = service.list_races()
    assert [(r["deal_slug"], r["code"]) for r in result["races"]] == expected
    if expected:
        first = result["races"][0]
        assert {"deal_slug", "code", "title", "status", "start_at", "end_at"} <= set(first)


def test_list_races_filters_by_status_and_slug(service):
    fixture = load("deals.json")["deals"]
    active = [(d["slug"], r["code"]) for d in fixture for r in d.get("races", []) if r.get("status") == "active"]
    result = service.list_races(status="active")
    assert [(r["deal_slug"], r["code"]) for r in result["races"]] == active
    only_risex = service.list_races(slug="risex")
    assert all(r["deal_slug"] == "risex" for r in only_risex["races"])


def test_get_leaderboard_top_n_and_total(service):
    result = service.get_leaderboard("risex", "leaderboard", top=20)
    fixture = load("leaderboard_risex.json")
    assert result["race"] == fixture["race"]
    assert result["columns"] == fixture["columns"]
    assert len(result["entries"]) == 20
    assert result["total_entries"] == len(fixture["entries"]) == 155
    assert result["entries"][0] == fixture["entries"][0]
    assert result["entries"][0]["wallet"] == "0xde...9d4bf"  # truncated as upstream, never expanded
    assert_attribution(result, "https://cp0x.com/deals/risex")


def test_get_leaderboard_clamps_top_to_100_and_defaults_to_main_board(service):
    result = service.get_leaderboard("risex", top=500)
    assert len(result["entries"]) == 100
    assert result["race"]["code"] == "leaderboard"


# ---------- restrictions monitor ----------

def test_check_interface_restrictions_declared_layers_and_legend(service):
    result = service.check_interface_restrictions("Aave")
    assert result["interface"]["id"] == "aave"
    assert result["interface"]["url"] == "https://app.aave.com" or result["interface"]["url"].startswith("https://")
    declared = result["declared"]
    assert declared["geo_site"]["s"] == "tos_only"
    assert declared["geo_feature"]["s"] == "no"
    assert {"geo_site", "geo_feature", "screening", "vpn", "asset_filter", "tos"} <= set(declared)
    assert result["observed"] == []
    assert result["alternatives"] == [{"name": "aave.cp0x.com", "url": "https://aave.cp0x.com"}]
    assert result["data_version"] == "2026-10-11"
    assert "status_values" in result["legend"] and "layer_values" in result["legend"]
    assert result["page_url"].startswith("https://restricted.cp0x.com/")
    assert_attribution(result, "https://restricted.cp0x.com/")


def test_check_interface_restrictions_declared_country_list(service):
    result = service.check_interface_restrictions("polymarket", country="br")
    assert result["country"] == "BR"
    assert "BR" in result["declared"]["geo_site"]["countries"]
    assert result["declared"]["geo_site"]["s"] == "yes"
    assert result["observed"] == []
    assert "BR" in result["observed_note"]  # no probes from BR in the data: say so, do not infer


def test_check_interface_restrictions_observed_probe_for_country(service):
    result = service.check_interface_restrictions("centrifuge", country="au")
    assert len(result["observed"]) == 1
    probe = result["observed"][0]
    assert probe["country"] == "AU" and probe["http_status"] == 403 and probe["ui_state"] == "challenge"
    assert probe["at"] == "2026-10-09T05:50:05Z"
    assert probe["blocked"] is False  # a Cloudflare challenge is not a geo-block
    us = service.check_interface_restrictions("polymarket", country="US")
    assert any(p["blocked"] is True for p in us["observed"])


def test_check_interface_restrictions_unknown_protocol_lists_candidates(service):
    result = service.check_interface_restrictions("poly")
    assert result["interface"] is None
    assert "error" in result
    assert "polymarket" in [c["id"] for c in result["candidates"]]
    none = service.check_interface_restrictions("zzz-not-a-protocol")
    assert none["interface"] is None and none["candidates"] == []


def test_list_restricted_interfaces_for_country(service):
    us = service.list_restricted_interfaces("us")
    ids = {i["id"]: i for i in us["interfaces"]}
    assert us["country"] == "US"
    assert "lido" in ids and "polymarket" in ids
    assert "aave" not in ids and "centrifuge" not in ids
    assert ids["polymarket"]["observed_block"] is True
    assert ids["lido"]["observed_block"] is False
    assert "geo_feature" in ids["lido"]["declared_layers"]
    ua = {i["id"]: i for i in service.list_restricted_interfaces("UA")["interfaces"]}
    assert set(ua) == {"uniswap", "polymarket"}  # polymarket lists UA-Crimea/UA-DPR/UA-LPR: regional, not nationwide
    assert ua["uniswap"]["declared_status"] == "reported" and ua["uniswap"]["scope"] == "national"
    assert ua["polymarket"]["scope"] == "regional" and ua["polymarket"]["declared_layers"] == []
    assert_attribution(us, "https://restricted.cp0x.com/")


# ---------- x402 ----------

def test_list_x402_facilitators(service):
    result = service.list_x402_facilitators()
    assert len(result["facilitators"]) == 9
    assert {"id", "name", "url"} <= set(result["facilitators"][0])
    assert_attribution(result, "https://x402.cp0x.com/")


def test_list_cp0x_x402_resources_with_tag_filter(service):
    everything = service.list_cp0x_x402_resources()
    assert len(everything["resources"]) == 17
    tag = load("cp0x_resources.json")["items"][0]["tags"][0]
    filtered = service.list_cp0x_x402_resources(tag=tag.upper())
    assert 1 <= len(filtered["resources"]) <= 17
    assert all(tag.lower() in [t.lower() for t in r["tags"]] for r in filtered["resources"])
    assert_attribution(filtered, "https://x402.cp0x.com/")


# ---------- freshness ----------

def test_stale_cache_is_flagged_in_tool_result(service, http, clock):
    from cp0x_mcp import sources

    fresh = service.list_deals()
    assert fresh["stale"] is False
    clock.advance(sources.TTL_DEALS_S + 1)
    http.fail.add(sources.DEALS_URL)
    stale = service.list_deals()
    assert stale["stale"] is True
    assert stale["count"] == 30


def test_upstream_down_without_cache_is_a_structured_error(service, http):
    from cp0x_mcp import sources

    http.fail.add(sources.FACILITATORS_URL)
    result = service.list_x402_facilitators()
    assert result["facilitators"] == []
    assert "error" in result and "x402-api.cp0x.com" in result["error"]

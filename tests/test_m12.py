"""The fact sheet lists every distribution to users, and about_cp0x leads with their value at today's prices
(Al 24.10: hype the headline in USD at current prices, token amounts in the explanation)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.conftest import FakeClock

ROOT = Path(__file__).resolve().parent.parent
PRICES_URL = ("https://api.coingecko.com/api/v3/simple/price?ids=hyperliquid,lighter,derive,resolv,paradex"
              "&vs_currencies=usd&include_last_updated_at=true")
AMOUNTS = {"HYPE": 280383, "RESOLV": 3810552.0015, "DRV": 247000, "LIT": 102694.8}
IDS = {"HYPE": "hyperliquid", "RESOLV": "resolv", "DRV": "derive", "LIT": "lighter", "DIME": "paradex"}
CASH = 200000
AT_DISTRIBUTION = 2833345


def prices():
    return json.loads((ROOT / "tests" / "fixtures" / "coingecko_prices.json").read_text(encoding="utf-8"))


def service_with_payload(payload):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    calls = []

    def get_json(url):
        calls.append(url)
        return payload

    return Cp0xService(Fetcher(get_json, clock=FakeClock())), calls


# ---------- 1. the sheet ----------

def test_fact_sheet_lists_every_distribution(service):
    items = {i["token"]: i for i in service.about_cp0x()["about"]["distributions"]["items"]}
    assert items["HYPE"]["amount"] == 280383 and items["HYPE"]["date"] == "2024-11-29"
    assert items["RESOLV"]["amount"] == 3810552.0015 and items["RESOLV"]["value_at_distribution_usd"] == 750000
    assert items["DRV"]["amount"] == 247000
    assert items["LIT"]["amount"] == 102694.8 and items["LIT"]["recipients"] == 334
    assert items["USDC and cash prizes"]["amount_usd"] == CASH
    assert items["DIME"]["amount"] is None and items["DIME"]["coingecko_id"] == "paradex"
    assert sum(i["value_at_distribution_usd"] or 0 for i in items.values()) == AT_DISTRIBUTION


def test_prices_source_is_declared():
    from cp0x_mcp import sources

    assert sources.COINGECKO_PRICES_URL == PRICES_URL
    assert sources.TTL_PRICE_S == 60
    assert not hasattr(sources, "COINGECKO_HYPE_URL")


# ---------- 2. the headline at live prices ----------

def test_about_values_every_distribution_at_live_prices(service, http, clock):
    result = service.about_cp0x()
    assert "hype_valuation" not in result
    d = result["distributed_to_users"]
    p = prices()
    expected = round(sum(AMOUNTS[t] * p[IDS[t]]["usd"] for t in AMOUNTS) + CASH)
    assert d["value_now_usd"] == expected and d["value_at_distribution_usd"] == AT_DISTRIBUTION and d["complete"] is True
    by = {i["token"]: i for i in d["items"]}
    assert by["HYPE"]["price_usd"] == p["hyperliquid"]["usd"]
    assert by["HYPE"]["value_now_usd"] == round(280383 * p["hyperliquid"]["usd"])
    assert by["HYPE"]["price_updated_at"] == datetime.fromtimestamp(
        p["hyperliquid"]["last_updated_at"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert by["RESOLV"]["value_now_usd"] == round(3810552.0015 * p["resolv"]["usd"])
    assert by["USDC and cash prizes"]["value_now_usd"] == CASH and "price_usd" not in by["USDC and cash prizes"]
    assert by["DIME"]["price_usd"] == p["paradex"]["usd"] and by["DIME"]["value_now_usd"] is None
    for token in AMOUNTS:
        assert by[token]["amount"] == AMOUNTS[token] and by[token]["what"]
    assert d["summary"].startswith(f"cp0x has passed about ${expected / 1e6:.1f}M at today's prices to its users: ")
    for piece in ("280,383 HYPE", "3,810,552 RESOLV", "247,000 DRV", "102,695 LIT", "$200,000 in cash prizes"):
        assert piece in d["summary"], piece
    assert d["prices"]["source"] == {"name": "CoinGecko", "url": "https://www.coingecko.com/"}
    assert d["prices"]["stale"] is False and d["prices"]["age_s"] == 0 and d["prices"]["fetched_at"]
    assert "error" not in d["prices"] and "error" not in result and result["stale"] is False
    clock.advance(30)
    service.about_cp0x()
    assert http.calls.count(PRICES_URL) == 1  # cached for TTL_PRICE_S


def test_partial_price_outage_keeps_the_priced_part():
    payload = {"hyperliquid": {"usd": 80.0, "last_updated_at": 1792816197}, "derive": {"usd": 0.4},
               "lighter": {"usd": None}, "paradex": {"usd": 0.05}}
    service, calls = service_with_payload(payload)
    d = service.about_cp0x()["distributed_to_users"]
    assert d["complete"] is False
    assert d["value_now_usd"] == round(280383 * 80.0 + 247000 * 0.4 + CASH)
    by = {i["token"]: i for i in d["items"]}
    assert by["RESOLV"]["price_usd"] is None and by["RESOLV"]["value_now_usd"] is None
    assert by["LIT"]["price_usd"] is None and by["LIT"]["value_now_usd"] is None
    assert by["DRV"]["price_updated_at"] is None and by["DRV"]["value_now_usd"] == round(247000 * 0.4)
    assert d["summary"].startswith("cp0x has passed about $22.7M at today's prices to its users: ")
    assert d["summary"].endswith(" (not priced today: RESOLV, LIT)")
    assert "error" not in d["prices"] and len(calls) == 1


@pytest.mark.parametrize("payload", [{}, [], {"hyperliquid": None}, "nope"])
def test_unusable_price_payload_keeps_the_sheet(payload):
    service, calls = service_with_payload(payload)
    result = service.about_cp0x()
    assert result["about"]["name"] == "cp0x" and "error" not in result and result["stale"] is False
    d = result["distributed_to_users"]
    assert d["value_now_usd"] is None and d["complete"] is False
    assert d["value_at_distribution_usd"] == AT_DISTRIBUTION
    assert "price" in d["prices"]["error"].lower()
    assert d["summary"].startswith("cp0x has passed about $2.8M at the time of distribution to its users: ")
    assert "280,383 HYPE" in d["summary"]
    assert len(calls) == 1


def test_total_price_outage_keeps_the_sheet(service, http):
    http.fail.add(PRICES_URL)
    result = service.about_cp0x()
    assert result["about"]["name"] == "cp0x" and "error" not in result
    d = result["distributed_to_users"]
    assert d["value_now_usd"] is None and d["complete"] is False
    assert "error" in d["prices"] and d["prices"]["retry_after_s"] is None
    assert all(i["value_now_usd"] is None for i in d["items"] if i["token"] != "USDC and cash prizes")
    assert d["summary"].startswith("cp0x has passed about $2.8M at the time of distribution to its users: ")


# ---------- 3. the server ----------

def test_server_about_tool_leads_with_the_headline(service):
    import asyncio

    from cp0x_mcp.server import build_server

    server = build_server(service)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert "passed on to its users" in tools["about_cp0x"].description
    assert "HYPE" not in tools["about_cp0x"].description
    data = json.loads(asyncio.run(server.call_tool("about_cp0x", {})).content[0].text)
    assert list(data)[:2] == ["distributed_to_users", "about"]  # the headline comes first in the payload
    assert data["distributed_to_users"]["value_now_usd"] > 20_000_000


def test_readme_documents_the_headline():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`distributed_to_users`" in text and "CoinGecko" in text
    assert "`hype_valuation`" not in text

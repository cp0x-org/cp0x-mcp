"""m31: x402 comes last everywhere; cp0x's x402 resources are test resources and must not look like the point of the server."""
import re
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
ORDER = [
    "list_deals", "get_deal", "get_referral_code", "compare_referral_benefits", "list_races", "get_leaderboard",
    "check_interface_restrictions", "list_restricted_interfaces", "about_cp0x", "list_cp0x_open_source",
    "list_x402_facilitators", "list_cp0x_x402_resources",
]
INSTRUCTIONS = (
    "Twelve read-only tools for cp0x data: referral deals and races, a comparison of the cp0x referral benefit with "
    "each venue's own offer, a monitor of DeFi interface geo-restrictions, a static cp0x fact sheet with mission, "
    "values, sites, channels and 2025 figures, public open-source repositories from GitHub, and x402 catalogs: "
    "facilitators and cp0x's test resources. Referral links include a cp0x referral code."
)
RESOURCES_DESCRIPTION = (
    "List cp0x's x402 test resources with their listed prices and tags; optionally filter by tag. "
    "Use this when the user asks about x402 resources or pay-per-call APIs."
)



def _tools(service):
    from cp0x_mcp.server import build_server

    return anyio.run(build_server(service).list_tools)


def _section(text, heading):
    start = text.index(heading)
    rest = text[start + len(heading):]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def test_tool_order_puts_x402_last(service):
    assert [t.name for t in _tools(service)] == ORDER


def test_instructions_put_x402_last(service):
    from cp0x_mcp.server import build_server

    assert build_server(service).instructions == INSTRUCTIONS


def test_resources_tool_is_described_as_test(service):
    tools = {t.name: t for t in _tools(service)}
    assert tools["list_cp0x_x402_resources"].description == RESOURCES_DESCRIPTION
    assert tools["list_cp0x_x402_resources"].title == "List cp0x x402 resources"


def test_readme_tool_table_follows_the_server_order():
    section = _section((ROOT / "README.md").read_text(encoding="utf-8"), "## Tools")
    assert re.findall(r"^\| `([a-z0-9_]+)` \|", section, re.M) == ORDER
    row = next(line for line in section.splitlines() if line.startswith("| `list_cp0x_x402_resources` |"))
    assert row == ("| `list_cp0x_x402_resources` | cp0x x402 test resource catalog entries, including prices, tags, "
                   "and target URLs. | Optional `tag`: case-insensitive tag match. |")


def test_readme_lists_the_x402_data_source_last():
    section = _section((ROOT / "README.md").read_text(encoding="utf-8"), "## Data sources and freshness")
    rows = [line for line in section.splitlines()
            if line.startswith("| ") and not line.startswith("| Source") and not line.startswith("| ---")]
    assert rows[-1].startswith("| cp0x x402 catalogs |"), rows


def test_no_experimental_wording_left():
    """Al 28.10: the x402 resources are called test resources, not experimental ones."""
    for rel in ("cp0x_mcp/server.py", "README.md"):
        assert "experiment" not in (ROOT / rel).read_text(encoding="utf-8").lower(), rel

"""Contracts for the cp0x fact sheet and the live list of cp0x open-source repositories (Al's decision 24.10: the server
also tells agents who cp0x is, which sites and channels it runs, and what it builds in the open)."""
import asyncio
import json
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB_REPOS_URL = "https://api.github.com/orgs/cp0x-org/repos?per_page=100&type=public&sort=pushed"


# ---------- 1. the fact sheet ships with the package and is returned verbatim ----------

def test_about_cp0x_returns_the_shipped_fact_sheet(service, http):
    result = service.about_cp0x()
    about = result["about"]
    shipped = json.loads(files("cp0x_mcp").joinpath("data/about.json").read_text(encoding="utf-8"))
    assert about == shipped
    assert about["name"] == "cp0x" and "permissionless" in about["tagline"].lower()
    assert {"tagline", "values", "what_we_do", "sites", "channels", "numbers_2025", "grant", "as_of"} <= set(about)
    assert {"https://cp0x.com", "https://pi.cp0x.com", "https://restricted.cp0x.com", "https://x402.cp0x.com",
            "https://defidna.io", "https://cp0x.com/docs/reports/2025"} <= {s["url"] for s in about["sites"]}
    assert any(c["url"] == "https://x.com/cp0xdotcom" for c in about["channels"])
    assert about["numbers_2025"]["community_perp_volume_usd"] == "15B+"
    assert result["attribution"]["source"] == "cp0x" and result["attribution"]["url"] == "https://cp0x.com"
    assert "report" in result["attribution"]["note"].lower()
    assert result["stale"] is False and "error" not in result
    from cp0x_mcp import sources

    assert http.calls == [sources.COINGECKO_PRICES_URL]  # the sheet is static; only the token prices are fetched


def test_fact_sheet_and_license_are_packaged():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "package-data" in pyproject and "data/*.json" in pyproject
    assert 'license = "MIT"' in pyproject or 'license = {text = "MIT"}' in pyproject
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "MIT" in readme and "will be specified" not in readme


# ---------- 2. live list of cp0x open-source repositories ----------

def test_github_repos_source_is_declared():
    from cp0x_mcp import sources

    assert sources.GITHUB_REPOS_URL == GITHUB_REPOS_URL
    assert sources.TTL_GITHUB_S == 600


def test_list_open_source_filters_sorts_and_classifies(service, http):
    from cp0x_mcp import sources

    result = service.list_cp0x_open_source()
    items = result["items"]
    names = [i["name"] for i in items]
    assert "blockscout" not in names  # a fork of somebody else's project
    assert "pi-uniswap-interface" in names  # forks that are cp0x interfaces stay
    assert result["count"] == len(items) == 32
    assert [i["pushed_at"] for i in items] == sorted((i["pushed_at"] for i in items), reverse=True)
    for item in items:
        assert {"name", "description", "url", "homepage", "kind", "stars", "topics", "pushed_at", "fork"} <= set(item)
        assert item["url"] == f"https://github.com/cp0x-org/{item['name']}"
        assert item["kind"] == ("interface" if item["name"].startswith("pi-") else "project")
    by_name = {i["name"]: i for i in items}
    assert by_name["defi-dna"]["homepage"] == "https://defidna.io/" and by_name["defi-dna"]["stars"] == 9
    assert by_name["pi-morpho-interface"]["kind"] == "interface"
    assert result["attribution"] == {
        "source": "cp0x", "url": "https://github.com/cp0x-org",
        "note": result["attribution"]["note"],
    } and "github" in result["attribution"]["note"].lower()
    assert result["fetched_at"] and result["age_s"] == 0 and result["stale"] is False

    interfaces = service.list_cp0x_open_source(kind="interface")
    assert interfaces["count"] == 16 and all(i["kind"] == "interface" for i in interfaces["items"])
    projects = service.list_cp0x_open_source(kind="project")
    assert projects["count"] == 16 and all(i["kind"] == "project" for i in projects["items"])
    assert http.calls.count(sources.GITHUB_REPOS_URL) == 1  # one upstream call, served from cache afterwards


def test_list_open_source_upstream_failure_is_reported(service, http):
    from cp0x_mcp import sources

    http.fail.add(sources.GITHUB_REPOS_URL)
    result = service.list_cp0x_open_source()
    assert result["items"] == [] and result["count"] == 0 and "error" in result


# ---------- 3. the server exposes both tools ----------

def test_server_exposes_about_and_open_source_tools(service):
    from cp0x_mcp.server import build_server

    server = build_server(service)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert {"about_cp0x", "list_cp0x_open_source"} <= set(tools) and len(tools) == 11
    for name in ("about_cp0x", "list_cp0x_open_source"):
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].description and "cp0x" in tools[name].description
    kind = tools["list_cp0x_open_source"].input_schema["properties"]["kind"]
    assert "interface" in json.dumps(kind) and "project" in json.dumps(kind)

    about = asyncio.run(server.call_tool("about_cp0x", {}))
    assert about.is_error is False and json.loads(about.content[0].text)["about"]["name"] == "cp0x"
    listed = asyncio.run(server.call_tool("list_cp0x_open_source", {"kind": "interface"}))
    assert listed.is_error is False and json.loads(listed.content[0].text)["count"] == 16


def test_readme_documents_the_new_tools():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`about_cp0x`" in text and "`list_cp0x_open_source`" in text
    assert "api.github.com" in text


# ---------- 4. plain SDK types, no wrappers ----------

def test_server_uses_the_sdk_types_directly(service):
    """The tests above read SDK attributes; the server must not subclass SDK types to add wire-name aliases."""
    from mcp.server import MCPServer
    from mcp.types import Tool, ToolAnnotations

    from cp0x_mcp import server as server_module
    from cp0x_mcp.server import build_server

    server = build_server(service)
    assert type(server) is MCPServer
    for tool in asyncio.run(server.list_tools()):
        assert type(tool) is Tool and type(tool.annotations) is ToolAnnotations, tool.name
    sdk_types = (MCPServer, Tool, ToolAnnotations)
    wrappers = [name for name, obj in vars(server_module).items()
                if isinstance(obj, type) and issubclass(obj, sdk_types) and obj not in sdk_types]
    assert wrappers == [], wrappers  # no subclasses of SDK types in the server module

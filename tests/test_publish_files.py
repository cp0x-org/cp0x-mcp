"""Contract of the publication files: server.json for the MCP Registry, Dockerfile, README, glama.json.

Facts pinned from the registry docs (checked 23.10.2026): remote-only servers publish metadata without a package, schema
2025-12-11, one remotes entry of type streamable-http, description limited to 100 characters.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_server_json_for_registry():
    data = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert data["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert data["name"] == "com.cp0x/public-data"
    assert data["title"]
    assert 1 <= len(data["description"]) <= 100
    assert data["version"] == "0.1.0"
    assert data["repository"] == {"url": "https://github.com/cp0x-org/cp0x-mcp", "source": "github"}
    assert data["remotes"] == [{"type": "streamable-http", "url": "https://mcp.cp0x.com/mcp"}]
    assert "packages" not in data


def test_glama_json_points_at_maintainer():
    data = json.loads((ROOT / "glama.json").read_text(encoding="utf-8"))
    assert data["$schema"] == "https://glama.ai/mcp/schemas/server.json"
    assert data["maintainers"] == ["illlefr4u"]  # Glama claims need a personal GitHub username, not the org


def test_dockerfile_runs_http_transport_on_all_interfaces():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.1[0-9]", text, re.M)
    assert "pip install" in text and "uvicorn" in text
    assert "--transport http" in text and "--host 0.0.0.0" in text
    assert "--allowed-host mcp.cp0x.com" in text
    assert re.search(r"^EXPOSE 8000", text, re.M)
    assert "HEALTHCHECK" in text and "/health" in text


def test_readme_sections_and_facts():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("## Tools", "## Connect", "## Data sources and freshness", "## Rate limits", "## Run locally", "## Publish"):
        assert heading in text, heading
    for tool in (
        "list_deals", "get_deal", "get_referral_code", "list_races", "get_leaderboard",
        "check_interface_restrictions", "list_restricted_interfaces", "list_x402_facilitators", "list_cp0x_x402_resources",
    ):
        assert f"`{tool}`" in text, tool
    assert "https://mcp.cp0x.com/mcp" in text
    assert "No authentication" in text
    for client in ("Claude", "ChatGPT", "Cursor", "Perplexity"):
        assert client in text, client
    assert "60 requests/minute" in text or "60 requests per minute" in text
    assert "referral code" in text.lower()
    assert "mcp-publisher" in text


def test_pyproject_pins_runtime_dependencies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'mcp==2.3.0' in text or 'mcp>=2.3,<3' in text
    assert "uvicorn" in text
    assert 'cp0x-mcp = "cp0x_mcp.server:main"' in text

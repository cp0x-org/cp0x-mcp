"""m28: version 0.2.0 everywhere it is written down."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_0_2_0_everywhere():
    assert 'version = "0.2.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"version": "0.2.0"' in (ROOT / "server.json").read_text(encoding="utf-8")
    assert "version `0.2.0`" in (ROOT / "README.md").read_text(encoding="utf-8")
    server = (ROOT / "cp0x_mcp" / "server.py").read_text(encoding="utf-8")
    assert '"0.2.0"' in server and '"0.1.0"' not in server

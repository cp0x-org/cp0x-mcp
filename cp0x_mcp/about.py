"""Load the static cp0x fact sheet shipped with the package."""

import json
from functools import cache
from importlib.resources import files


@cache
def load_fact_sheet() -> dict:
    """Read the packaged fact sheet once and keep it in memory."""
    return json.loads(
        files("cp0x_mcp").joinpath("data/about.json").read_text(encoding="utf-8")
    )

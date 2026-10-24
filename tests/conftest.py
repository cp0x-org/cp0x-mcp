"""Shared fixtures: fake upstream HTTP backed by JSON fixtures, controllable clock, service factory.

The package modules are imported lazily inside fixtures so that fixture-only tests still collect on the RED base.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeHTTP:
    """url -> fixture file; records calls; raises for urls in `fail`."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []
        self.fail: set[str] = set()

    def __call__(self, url: str):
        self.calls.append(url)
        if url in self.fail:
            raise ConnectionError(f"simulated failure for {url}")
        if url not in self.routes:
            raise KeyError(f"unexpected url {url}")
        return load(self.routes[url])


def routes_for_sources():
    from cp0x_mcp import sources

    return {
        sources.DEALS_URL: "deals.json",
        sources.race_url("risex", "leaderboard"): "leaderboard_risex.json",
        sources.MONITOR_INTERFACES_URL: "monitor_interfaces.json",
        sources.MONITOR_OBSERVATIONS_URL: "monitor_observations.json",
        sources.FACILITATORS_URL: "facilitators.json",
        sources.RESOURCES_URL: "cp0x_resources.json",
        **({getattr(sources, "GITHUB_REPOS_URL"): "github_repos.json"} if hasattr(sources, "GITHUB_REPOS_URL") else {}),
        **({getattr(sources, "COINGECKO_PRICES_URL"): "coingecko_prices.json"} if hasattr(sources, "COINGECKO_PRICES_URL") else {}),
    }


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def http():
    return FakeHTTP(routes_for_sources())


@pytest.fixture
def service(http, clock):
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    return Cp0xService(Fetcher(http, clock=clock))

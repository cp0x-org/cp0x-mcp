"""Plain JSON-compatible results for the cp0x data tools."""

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from . import sources
from .about import load_fact_sheet
from .referral import code_hint
from .upstream import Fetcher, UpstreamError


_HOME = "https://cp0x.com/"
_MONITOR = "https://restricted.cp0x.com/"
_X402 = "https://x402.cp0x.com/"
_NOTE = (
    "Data from cp0x public endpoints; referral links contain a cp0x referral code."
)
_RACE_FIELDS = ("code", "title", "status", "start_at", "end_at")
_GEO_FIELDS = ("geo_site", "geo_feature")
_DECLARED_FIELDS = (*_GEO_FIELDS, "screening", "vpn", "asset_filter", "tos", "kyc")
_PROBE_FIELDS = (
    "country", "kind", "url", "http_status", "final_url", "ui_state", "flags", "at"
)


def _pick(record: dict, fields: tuple[str, ...]) -> dict:
    return {field: record.get(field) for field in fields}


def _compact_deal(deal: dict) -> dict:
    result = _pick(deal, ("slug", "title", "bonus", "link", "page_url"))
    code = deal.get("code")
    result["code"] = code if isinstance(code, str) and code else None
    result["code_hint"] = code_hint(deal.get("link") or "")
    result["races"] = [_pick(race, _RACE_FIELDS) for race in deal.get("races", [])]
    return result


def _blocked(probe: dict) -> bool:
    return probe.get("ui_state") == "blocked" or (
        probe.get("flags") or {}
    ).get("blocked") is True


def _result(page_url: str) -> dict:
    return {
        "attribution": {"source": "cp0x", "url": page_url, "note": _NOTE},
        "stale": False,
        "fetched_at": None,
        "age_s": None,
        "stale_since": None,
    }


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _country_code(country: str) -> str:
    if not isinstance(country, str) or re.fullmatch(r"[A-Za-z]{2}", country.strip()) is None:
        raise ValueError("invalid country")
    return country.strip().upper()


def _country_layers(interface: dict, country: str) -> tuple[list[str], list[str], dict[str, str]]:
    declared, close_only, regions = [], [], {}
    for layer in _GEO_FIELDS:
        status = interface.get(layer) or {}
        countries = status.get("countries") or []
        closing = status.get("close_only") or []
        if country in countries:
            declared.append(layer)
        if country in closing:
            close_only.append(layer)
        for code in [*countries, *closing]:
            if code.startswith(f"{country}-") and code not in regions:
                regions[code] = layer
    return declared, close_only, regions


def _country_status(interface: dict, layers: list[str], close_only: list[str], regions: dict[str, str]) -> str | None:
    layer = next(iter(layers or close_only or regions.values()), None)
    return interface[layer].get("s") if layer is not None else None


class Cp0xService:
    def __init__(self, fetcher: Fetcher):
        self._fetcher = fetcher

    def about_cp0x(self) -> dict:
        return {
            "about": deepcopy(load_fact_sheet()),
            "attribution": {
                "source": "cp0x",
                "url": "https://cp0x.com",
                "note": (
                    "Static fact sheet shipped with the server; "
                    "figures from the cp0x 2025 annual report"
                ),
            },
            "stale": False,
        }

    def list_cp0x_open_source(
        self, kind: Literal["interface", "project"] | None = None,
    ) -> dict:
        data, result = self._read(
            [(sources.GITHUB_REPOS_URL, sources.TTL_GITHUB_S)],
            "https://github.com/cp0x-org",
        )
        result["attribution"]["note"] = (
            "Public repositories of the cp0x-org GitHub organization"
        )
        items = []
        for repo in data[0] if data else []:
            repo_kind = "interface" if repo["name"].startswith("pi-") else "project"
            if repo.get("archived") or repo.get("private"):
                continue
            if repo.get("fork") and repo_kind != "interface":
                continue
            if kind is not None and repo_kind != kind:
                continue
            items.append({
                **_pick(repo, ("name", "description", "homepage", "topics", "pushed_at", "fork")),
                "url": repo.get("html_url"),
                "kind": repo_kind,
                "stars": repo.get("stargazers_count"),
            })
        items.sort(key=lambda item: item["pushed_at"] or "", reverse=True)
        result.update(items=items, count=len(items))
        return result

    def _read(self, endpoints: list[tuple[str, int]], page_url: str) -> tuple[list[Any], dict]:
        """Collect freshness and turn upstream failures into result metadata."""
        result = _result(page_url)
        data = []
        responses = []
        for url, ttl in endpoints:
            try:
                fetched = self._fetcher.get(url, ttl)
            except UpstreamError as exc:
                result["error"] = str(exc)
                result["retry_after_s"] = exc.retry_after_s
                break
            result["stale"] = result["stale"] or fetched.stale
            responses.append((fetched, ttl))
            data.append(fetched.data)
        if responses:
            oldest, ttl = min(responses, key=lambda response: response[0].fetched_at)
            result["fetched_at"] = _utc(oldest.fetched_wall)
            result["age_s"] = max(self._fetcher.age_s(fetched) for fetched, _ in responses)
            if result["stale"]:
                result["stale_since"] = _utc(oldest.fetched_wall + ttl)
        return data, result

    def _deals(self) -> tuple[list[dict], dict]:
        data, result = self._read([(sources.DEALS_URL, sources.TTL_DEALS_S)], _HOME)
        return data[0].get("deals", []) if data else [], result

    def _monitor(self) -> tuple[list[Any], dict]:
        return self._read([
            (sources.MONITOR_INTERFACES_URL, sources.TTL_MONITOR_S),
            (sources.MONITOR_OBSERVATIONS_URL, sources.TTL_MONITOR_S),
        ], _MONITOR)

    def list_deals(self, query: str | None = None, limit: int | None = None) -> dict:
        deals, result = self._deals()
        if query is not None:
            needle = query.casefold()
            deals = [
                deal for deal in deals
                if any(needle in deal.get(key, "").casefold() for key in ("title", "slug"))
            ]
        result["count"] = len(deals)
        result["deals"] = [_compact_deal(deal) for deal in deals[:limit]]
        return result

    def get_deal(self, slug: str) -> dict:
        deals, result = self._deals()
        result["deal"] = None
        if "error" in result:
            return result
        for deal in deals:
            if deal.get("slug") == slug:
                result["deal"] = deal
                result["attribution"]["url"] = deal.get("page_url") or _HOME
                return result
        result["error"] = f"Unknown deal slug: {slug}"
        result["known_slugs"] = [deal.get("slug") for deal in deals]
        return result

    def get_referral_code(self, venue: str) -> dict:
        deals, result = self._deals()
        result.update(match=None, candidates=[])
        if "error" in result:
            return result
        needle = venue.strip().casefold()
        exact = [
            deal for deal in deals
            if any(needle == deal.get(key, "").strip().casefold() for key in ("title", "slug"))
        ]
        matches = exact or [
            deal for deal in deals
            if any(needle in deal.get(key, "").casefold() for key in ("title", "slug"))
        ]
        if len(matches) == 1:
            result["match"] = _compact_deal(matches[0])
            result["attribution"]["url"] = matches[0].get("page_url") or _HOME
        elif matches:
            result["candidates"] = [_pick(deal, ("slug", "title")) for deal in matches]
        else:
            result["error"] = f"No venue matches: {venue}"
        return result

    def list_races(self, status: str | None = None, slug: str | None = None) -> dict:
        deals, result = self._deals()
        result["races"] = [
            {"deal_slug": deal.get("slug"), **_pick(race, _RACE_FIELDS)}
            for deal in deals
            if slug is None or deal.get("slug") == slug
            for race in deal.get("races", [])
            if status is None or race.get("status") == status
        ]
        return result

    def get_leaderboard(self, slug: str, race_code: str = "leaderboard", top: int = 20) -> dict:
        try:
            url = sources.race_url(slug, race_code)
        except ValueError as exc:
            result = _result(_HOME)
            result.update(error=str(exc), race=None, columns=[], entries=[], total_entries=0)
            return result
        data, result = self._read(
            [(url, sources.TTL_RACES_S)],
            f"https://cp0x.com/deals/{slug}",
        )
        result.update(race=None, columns=[], entries=[], total_entries=0)
        if "error" not in result:
            board = data[0]
            entries = board.get("entries", [])
            result.update(
                race=board.get("race"),
                columns=board.get("columns", []),
                entries=entries[:max(1, min(100, top))],
                total_entries=len(entries),
            )
        return result

    def check_interface_restrictions(self, protocol: str, country: str | None = None) -> dict:
        if country is not None:
            try:
                country = _country_code(country)
            except ValueError as exc:
                result = _result(_MONITOR)
                result.update(error=str(exc), interface=None, country=country, country_match=None,
                              candidates=[], observed=[], page_url=_MONITOR)
                return result
        data, result = self._monitor()
        result.update(interface=None, country=country, country_match=None,
                      candidates=[], observed=[], page_url=_MONITOR)
        if "error" in result:
            return result
        catalog, observations = data
        meta = catalog.get("meta", {})
        result["data_version"] = meta.get("generated")
        result["legend"] = _pick(meta, ("status_values", "layer_values"))
        needle = protocol.strip().casefold()
        interfaces = catalog.get("interfaces", [])
        interface = next((
            item for item in interfaces
            if any(needle == item.get(key, "").casefold() for key in ("id", "name"))
        ), None)
        if interface is None:
            result["candidates"] = [
                _pick(item, ("id", "name")) for item in interfaces
                if any(needle in item.get(key, "").casefold() for key in ("id", "name"))
            ]
            result["error"] = f"No exact interface match: {protocol}"
            return result
        result["interface"] = _pick(interface, ("id", "name", "url", "category"))
        result["declared"] = _pick(interface, _DECLARED_FIELDS)
        result["declared"].update({
            key: value for key, value in interface.items()
            if isinstance(value, dict) and "s" in value
        })
        if country is not None:
            layers, close_only, regions = _country_layers(interface, country)
            result["country_match"] = {
                "national": bool(layers), "close_only": bool(close_only), "regions": list(regions),
                "status": _country_status(interface, layers, close_only, regions),
            }
        result["alternatives"] = interface.get("alternatives", [])
        result["observed"] = [
            {**_pick(probe, _PROBE_FIELDS), "blocked": _blocked(probe)}
            for probe in observations.get("observations", [])
            if probe.get("interface_id") == interface.get("id")
            and (country is None or probe.get("country") == country)
        ]
        if not result["observed"]:
            location = f" from {country}" if country is not None else ""
            result["observed_note"] = (
                f"No probes{location} in the monitor data, version {meta.get('generated')}"
            )
        return result

    def list_restricted_interfaces(self, country: str) -> dict:
        try:
            country = _country_code(country)
        except ValueError as exc:
            result = _result(_MONITOR)
            result.update(error=str(exc), country=country, interfaces=[])
            return result
        data, result = self._monitor()
        result.update(country=country, interfaces=[])
        if "error" in result:
            return result
        catalog, observations = data
        blocked_ids = {
            probe.get("interface_id")
            for probe in observations.get("observations", [])
            if probe.get("country") == country and _blocked(probe)
        }
        for interface in catalog.get("interfaces", []):
            layers, close_only, regions = _country_layers(interface, country)
            observed_block = interface.get("id") in blocked_ids
            if layers or close_only or regions or observed_block:
                result["interfaces"].append({
                    **_pick(interface, ("id", "name", "url")),
                    "declared_layers": layers,
                    "declared_status": _country_status(interface, layers, close_only, regions),
                    "close_only_layers": close_only,
                    "regions": list(regions),
                    "observed_block": observed_block,
                    "scope": (
                        "national" if layers else "close_only" if close_only
                        else "regional" if regions else "observed"
                    ),
                })
        return result

    def list_x402_facilitators(self) -> dict:
        data, result = self._read(
            [(sources.FACILITATORS_URL, sources.TTL_X402_S)], _X402
        )
        result["facilitators"] = data[0] if data else []
        return result

    def list_cp0x_x402_resources(self, tag: str | None = None) -> dict:
        data, result = self._read(
            [(sources.RESOURCES_URL, sources.TTL_X402_S)], _X402
        )
        items = data[0].get("items", []) if data else []
        if tag is not None:
            items = [
                item for item in items
                if tag.casefold() in [value.casefold() for value in item.get("tags", [])]
            ]
        result["resources"] = items
        return result

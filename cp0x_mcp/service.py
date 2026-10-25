"""Plain JSON-compatible results for the cp0x data tools."""

import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from . import sources
from .about import load_fact_sheet
from .benefits import calculate_benefit, calculate_race_cases, load_benefits, today_utc
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


def _merge_freshness(result: dict, freshness: dict) -> None:
    """Include another source's oldest timestamps, greatest age and stale flag."""
    for field, aggregate in (("fetched_at", min), ("age_s", max), ("stale_since", min)):
        values = [value for value in (result.get(field), freshness.get(field)) if value is not None]
        result[field] = aggregate(values) if values else None
    result["stale"] = result["stale"] or freshness["stale"]


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
    def __init__(self, fetcher: Fetcher, benefits=None, today=None):
        self._fetcher = fetcher
        self._benefits = load_benefits() if benefits is None else benefits
        self._today = today_utc if today is None else today

    def about_cp0x(self) -> dict:
        about = deepcopy(load_fact_sheet())
        source_url = "https://www.coingecko.com/"
        data, prices = self._read(
            [(sources.COINGECKO_PRICES_URL, sources.TTL_PRICE_S)], source_url,
        )
        prices.pop("attribution")
        prices["source"] = {"name": "CoinGecko", "url": source_url}
        payload = data[0] if data and isinstance(data[0], dict) else {}
        items, pieces, unpriced = [], [], []
        any_price = False
        for distribution in about["distributions"]["items"]:
            item = _pick(distribution, ("token", "what"))
            if "amount_usd" in distribution:
                amount_usd = distribution["amount_usd"]
                item.update(amount_usd=amount_usd, value_now_usd=amount_usd)
                pieces.append(f"${amount_usd:,} in cash prizes")
            else:
                amount = distribution.get("amount")
                has_amount = isinstance(amount, (int, float)) and not isinstance(amount, bool)
                item.update(amount=amount, value_now_usd=None)
                usd = None
                if "coingecko_id" in distribution:
                    price = payload.get(distribution["coingecko_id"])
                    candidate = price.get("usd") if isinstance(price, dict) else None
                    if (
                        isinstance(candidate, (int, float))
                        and not isinstance(candidate, bool)
                        and math.isfinite(candidate)
                        and candidate > 0
                    ):
                        usd = candidate
                    item.update(price_usd=usd, price_updated_at=None)
                    updated_at = price.get("last_updated_at") if isinstance(price, dict) else None
                    if isinstance(updated_at, int) and not isinstance(updated_at, bool):
                        try:
                            item["price_updated_at"] = _utc(updated_at)
                        except (OverflowError, OSError, ValueError):
                            pass  # An unrepresentable timestamp does not invalidate the price.
                if has_amount:
                    pieces.append(f"{round(amount):,} {item['token']}")
                    if usd is None:
                        unpriced.append(item["token"])
                    else:
                        item["value_now_usd"] = round(amount * usd)
                        any_price = True
            items.append(item)
        if not any_price and "error" not in prices:
            prices["error"] = "unusable price response"
        value_now_usd = (
            round(sum(item["value_now_usd"] or 0 for item in items)) if any_price else None
        )
        value_at_distribution_usd = sum(
            item["value_at_distribution_usd"] or 0 for item in about["distributions"]["items"]
        )
        if value_now_usd is not None:
            price_basis = (
                f"at cached prices from {prices['fetched_at'][:10]}"
                if prices["stale"] else "at today's prices"
            )
            summary = f"cp0x has passed about ${value_now_usd / 1e6:.1f}M {price_basis} to its users: "
        else:
            summary = (
                f"cp0x has passed about ${value_at_distribution_usd / 1e6:.1f}M "
                "at the time of distribution to its users: "
            )
        summary += ", ".join(pieces)
        if unpriced:
            summary += f" (not priced today: {', '.join(unpriced)})"
        return {
            "distributed_to_users": {
                "items": items,
                "value_now_usd": value_now_usd,
                "value_at_distribution_usd": value_at_distribution_usd,
                "complete": not unpriced,
                "summary": summary,
                "prices": prices,
            },
            "about": about,
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
        result.update(deal=None, benefit=None, race_cases=None)
        if "error" in result:
            return result
        for deal in deals:
            if deal.get("slug") == slug:
                result["deal"] = deal
                result["benefit"] = self._benefit(deal)
                result["race_cases"] = self._race_cases(deal, result["benefit"])
                if result["race_cases"] is not None:
                    _merge_freshness(result, result["race_cases"]["freshness"])
                result["attribution"]["url"] = deal.get("page_url") or _HOME
                return result
        result["error"] = f"Unknown deal slug: {slug}"
        result["known_slugs"] = [deal.get("slug") for deal in deals]
        return result

    def get_referral_code(self, venue: str) -> dict:
        deals, result = self._deals()
        result.update(match=None, candidates=[], benefit=None)
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
            result["benefit"] = self._benefit(matches[0])
            result["attribution"]["url"] = matches[0].get("page_url") or _HOME
        elif matches:
            result["candidates"] = [_pick(deal, ("slug", "title")) for deal in matches]
        else:
            result["error"] = f"No venue matches: {venue}"
        return result

    def _benefit(self, deal: dict) -> dict | None:
        record = self._benefits.get("venues", {}).get(deal.get("slug"))
        return calculate_benefit(record, self._today()) if record is not None else None

    def _race_cases(self, deal: dict, benefit: dict | None) -> dict | None:
        if benefit is None:
            return None
        boards = []
        for race in deal.get("races", []):
            if race.get("status") != "active":
                continue
            try:
                url = sources.race_url(deal["slug"], race["code"])
            except (KeyError, ValueError):
                return None
            data, metadata = self._read([(url, sources.TTL_RACES_S)], deal.get("page_url") or _HOME)
            if "error" in metadata:
                return None
            boards.append((data[0], metadata))
        if not boards:
            return None
        selected, selected_metadata = boards[0]
        largest_pool = None
        for board, metadata in boards:
            prize = (board.get("race") or {}).get("prize") or {}
            pool = prize.get("pool")
            if (prize.get("currency") == "USD" and isinstance(pool, (int, float))
                    and not isinstance(pool, bool) and math.isfinite(pool)
                    and (largest_pool is None or pool > largest_pool)):
                selected, largest_pool = board, pool
                selected_metadata = metadata
        result = calculate_race_cases(benefit, selected)
        if result is not None:
            result["freshness"] = _pick(
                selected_metadata, ("stale", "fetched_at", "age_s", "stale_since"),
            )
        return result

    def compare_referral_benefits(self, category: str | None = None) -> dict:
        """Compare the cp0x code with each venue's own offer in API order for ties."""
        deals, result = self._deals()
        items = []
        for deal in deals:
            benefit = self._benefit(deal)
            if category is not None and (benefit is None or benefit.get("category") != category):
                continue
            race_cases = self._race_cases(deal, benefit)
            if race_cases is not None:
                _merge_freshness(result, race_cases["freshness"])
            items.append({
                **_compact_deal(deal), "benefit": benefit,
                "race_cases": race_cases,
            })

        def order(item):
            benefit = item["benefit"] or {}
            delta = benefit.get("delta")
            better = [part for part in delta or [] if part["better"]]
            if not better:
                return (1 if delta is not None else 2, 0, 0, 0)
            saving = (benefit.get("per_10k_usd_traded") or {}).get("saving_vs_original_usd")
            gap = max(part["cp0x"] - part["original"] for part in better)
            return (0, saving is None, -saving if saving is not None else 0, -gap)

        items.sort(key=order)
        result.update(
            deals=items, category=category,
            cp0x_perks=load_fact_sheet().get("perks", []),
            note="Benefits compare the cp0x referral with each venue's own offer; missing data is not a zero benefit.",
        )
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

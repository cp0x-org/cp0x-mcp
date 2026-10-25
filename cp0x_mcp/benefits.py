"""Compare referral benefits and illustrate them with live race standings."""

import json
import math
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path


RACE_NOTE = "Prizes as of the current leaderboard; final standings can differ."
_FEE_KINDS = {"fee_discount", "fee_rebate"}


def load_benefits(path=None) -> dict:
    """Read the bundled benefit records, or a supplied JSON file."""
    source = Path(path) if path is not None else files("cp0x_mcp").joinpath("data/benefits.json")
    return json.loads(source.read_text(encoding="utf-8"))


def today_utc() -> date:
    """Return today's date in UTC."""
    return datetime.now(timezone.utc).date()


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _without_quotes(value):
    if isinstance(value, dict):
        return {key: _without_quotes(item) for key, item in value.items() if key != "quote"}
    if isinstance(value, list):
        return [_without_quotes(item) for item in value]
    return value


def _numeric_items(items: list[dict]) -> dict:
    totals = {}
    for item in items:
        if item.get("kind") in {"loyalty", "other"} or not _number(item.get("value")):
            continue
        pair = (item.get("kind"), item.get("unit"))
        totals[pair] = totals.get(pair, 0) + item["value"]
    return totals


def _fee_percent(items: list[dict]):
    values = [item["value"] for item in items
              if item.get("kind") in _FEE_KINDS and item.get("unit") == "%"
              and _number(item.get("value"))]
    return sum(values) if values else None


def calculate_benefit(record: dict, today: date) -> dict:
    """Compute comparable numeric benefits without changing the source record."""
    benefit = _without_quotes(record)
    cp0x_items = benefit.get("cp0x", [])
    original = benefit.get("original", {})
    original_items = [] if original.get("status") == "none" else original.get("items", [])
    cp0x_values = _numeric_items(cp0x_items)
    original_values = _numeric_items(original_items)
    unsized_original_kinds = {
        item.get("kind") for item in original_items if not _number(item.get("value"))
    }
    delta = None
    if (cp0x_values or original_values) and original.get("status") in {"found", "none"}:
        delta = []
        for kind, unit in dict.fromkeys([*cp0x_values, *original_values]):
            pair = (kind, unit)
            cp0x_value = cp0x_values.get(pair)
            original_value = original_values.get(pair, 0)
            note = None
            if cp0x_value is None:
                note = "not stated for the cp0x code"
            elif pair not in original_values and kind in unsized_original_kinds:
                original_value = None
                note = "original size not stated"
            comparable = cp0x_value is not None and original_value is not None
            comparison = {
                "kind": kind, "unit": unit, "cp0x": cp0x_value, "original": original_value,
                "better": comparable and cp0x_value > original_value,
                "worse": comparable and cp0x_value < original_value,
            }
            if note is not None:
                comparison["note"] = note
            delta.append(comparison)
    benefit["delta"] = delta
    benefit["per_10k_usd_traded"] = None
    taker_bps = benefit.get("taker_fee_bps")
    percent = _fee_percent(cp0x_items)
    if _number(taker_bps) and percent is not None:
        original_percent = _fee_percent(original_items)
        original_fee_unknown = original_percent is None and bool(_FEE_KINDS & unsized_original_kinds)
        benefit["per_10k_usd_traded"] = {
            "taker_fee_bps": taker_bps,
            "fees_source_url": benefit.get("fees_source_url"),
            "saving_usd": taker_bps * percent / 100,
            "saving_vs_original_usd": (
                taker_bps * (percent - (original_percent or 0)) / 100
                if original.get("status") in {"found", "none"} and not original_fee_unknown else None
            ),
        }
    try:
        benefit["stale"] = (today - date.fromisoformat(benefit["checked_at"])).days > 30
    except (KeyError, TypeError, ValueError):
        benefit["stale"] = True
    return benefit


def _base_benefits(items: list[dict]) -> list[str]:
    descriptions = []
    for item in items:
        if item.get("kind") in _FEE_KINDS:
            continue
        value = item.get("value")
        label = item.get("applies_to") or (item.get("kind") or "benefit").replace("_", " ")
        if _number(value):
            unit = item.get("unit") or ""
            descriptions.append(f"{value:+g}{unit} {label}")
        else:
            descriptions.append(label)
    return descriptions


def calculate_race_cases(benefit: dict, board: dict) -> dict | None:
    """Use the current first, tenth and last paid ranks as benefit examples."""
    ranked_by = next((column for column in board.get("columns", [])
                      if column in {"volume", "fees"}), None)
    prize_column = next((column for column in ("prize", "points")
                         if column in board.get("columns", [])), None)
    entries = sorted(
        (entry for entry in board.get("entries", []) if _number(entry.get("rank"))),
        key=lambda entry: entry["rank"],
    )
    if ranked_by is None or not entries:
        return None
    race = board.get("race") or {}
    prize = race.get("prize") or {}
    selected = [
        ("first", entries[0]),
        ("top10", next((entry for entry in entries if entry["rank"] == 10), entries[-1])),
    ]
    paid = [entry for entry in entries
            if _number(entry.get(prize_column)) and entry[prize_column] != 0]
    if paid:
        selected.append(("last_paid", paid[-1]))
    fee_items = [item for item in benefit.get("cp0x", [])
                 if item.get("kind") in _FEE_KINDS and item.get("unit") == "%"
                 and _number(item.get("value"))]
    percent = _fee_percent(fee_items)
    taker_bps = benefit.get("taker_fee_bps")
    cases = []
    for name, entry in selected:
        amount = entry.get(ranked_by)
        saving = None
        if percent is not None and _number(amount):
            if ranked_by == "fees":
                # Paid fees already include discounts; rebates use the paid amount directly.
                saving = sum(
                    amount * item["value"] / (
                        100 - item["value"] if item["kind"] == "fee_discount" else 100
                    )
                    for item in fee_items
                )
            elif _number(taker_bps):
                saving = amount * taker_bps / 10000 * percent / 100
        race_prize = entry.get(prize_column)
        cases.append({
            "case": name, "rank": entry["rank"], ranked_by: amount,
            "race_prize": race_prize, "base_saving_usd": saving,
            "total_usd": (
                saving + race_prize
                if saving is not None and prize.get("currency") == "USD" and _number(race_prize)
                else None
            ),
        })
    return {
        "race": {
            "code": race.get("code"), "title": race.get("title"), "ranked_by": ranked_by,
            "ends_at": race.get("end_at"),
            "prize_currency": prize.get("currency"), "prize_pool": prize.get("pool"),
            "leaderboard_updated": race.get("last_update"),
        },
        "cases": cases,
        "base_benefits": _base_benefits(benefit.get("cp0x", [])),
        "note": RACE_NOTE,
    }

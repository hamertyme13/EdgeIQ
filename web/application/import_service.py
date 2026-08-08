from __future__ import annotations

import csv
import json
from collections.abc import Callable
from io import StringIO

from models.bet import Bet
from repository.bet_repository import BetRepository
from services.betting import potential_profit
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import stat_key


def analyze_upload_payload(
    payload,
    *,
    decode: Callable[[str], bytes],
    is_image: Callable[[object], bool],
    analyze_image: Callable[[object, bytes], dict],
    analyze_text: Callable[[object, bytes], dict],
) -> dict:
    raw = decode(payload.content_base64)
    if is_image(payload):
        return analyze_image(payload, raw)
    return analyze_text(payload, raw)


def import_wizard_payload(sportsbook_integrations: Callable[[], dict]) -> dict:
    return {
        "title": "Account Sync Import Wizard",
        "summary": "Use screenshot, CSV, or JSON imports until PrizePicks and Underdog expose authenticated account APIs.",
        "steps": [
            {
                "label": "Choose platform",
                "detail": "Export or screenshot settled entries from PrizePicks or Underdog.",
            },
            {
                "label": "Upload file",
                "detail": "Use Screenshot + File Analyzer with target set to past bet history or final stats.",
            },
            {
                "label": "Review mapping",
                "detail": "Confirm player, stat, line, result, wager, and payout before calibration uses the row.",
            },
            {
                "label": "Recheck records",
                "detail": "Run Recheck Final Stats from Completed Entry History to clear unknown legs.",
            },
        ],
        "templates": [
            {
                "platform": "PrizePicks",
                "columns": ["date", "player", "sport", "stat", "line", "direction", "result", "wager", "payout"],
                "sample": "date,player,sport,stat,line,direction,result,wager,payout",
            },
            {
                "platform": "Underdog",
                "columns": ["date", "player", "sport", "stat", "line", "direction", "result", "wager", "payout"],
                "sample": "date,player,sport,stat,line,direction,result,wager,payout",
            },
        ],
        "sync_status": sportsbook_integrations(),
    }


def parse_betting_history(payload: str) -> list[dict]:
    stripped = payload.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            parsed = parsed.get("bets", [])
        return [dict(row) for row in parsed if isinstance(row, dict)]

    reader = csv.DictReader(StringIO(stripped))
    return [
        {
            (key or "").strip().lower().replace(" ", "_"): (value or "").strip()
            for key, value in row.items()
        }
        for row in reader
    ]


def import_betting_history_payload(payload: str, source: str) -> dict:
    imported = 0
    skipped = 0
    for row in parse_betting_history(payload):
        try:
            result = row.get("result", "").strip().title()
            wager = float(row.get("wager") or row.get("amount") or 0)
            if result not in {"Win", "Loss", "Push"} or wager <= 0:
                skipped += 1
                continue
            odds = int(float(row.get("odds") or -110))
            profit = _imported_profit(row, result, odds, wager)
            BetRepository().save(
                Bet(
                    sport=row.get("sport", ""),
                    game=row.get("game", ""),
                    description=row.get("description") or row.get("bet") or row.get("pick") or "Imported bet",
                    odds=odds,
                    wager=wager,
                    result=result,
                    profit=round(profit, 2),
                    platform=row.get("platform", source),
                    stat_type=row.get("stat_type") or row.get("stat", ""),
                    win_probability=float(row.get("win_probability") or row.get("probability") or 0),
                    source=source or "imported",
                )
            )
            imported += 1
        except (TypeError, ValueError):
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def deduplicate_uploaded_props(props: list[dict]) -> list[dict]:
    selected: dict[tuple, dict] = {}
    for prop in props:
        key = (
            canonical_person_key(prop.get("player")),
            str(prop.get("sport") or prop.get("league") or "").strip().upper(),
            stat_key(prop.get("stat")),
            _number_key(prop.get("line")),
            _direction_key(prop.get("direction") or prop.get("pick") or prop.get("side")),
            str(prop.get("platform") or "").strip().lower(),
        )
        if not key[0] or key[3] is None:
            continue
        existing = selected.get(key)
        if existing is None or _prop_quality(prop) > _prop_quality(existing):
            selected[key] = prop
    return list(selected.values())


def _imported_profit(row: dict, result: str, odds: int, wager: float) -> float:
    profit_value = row.get("profit")
    if profit_value not in (None, ""):
        return float(profit_value)
    if result == "Win":
        return potential_profit(odds, wager)
    if result == "Loss":
        return -wager
    return 0.0


def _number_key(value: object) -> float | None:
    try:
        return round(float(str(value)), 4)
    except (TypeError, ValueError):
        return None


def _direction_key(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"over", "higher", "more", "o"}:
        return "over"
    if text in {"under", "lower", "less", "u"}:
        return "under"
    return ""


def _prop_quality(prop: dict) -> tuple[int, int, int, int]:
    return (
        int(bool(prop.get("provider_backed"))),
        int(bool(prop.get("provider_player_id") or prop.get("player_id"))),
        int(bool(prop.get("game_time"))),
        int(bool(prop.get("game"))),
    )

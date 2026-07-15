from __future__ import annotations

import json
import os
import csv
from io import StringIO
from functools import lru_cache
from pathlib import Path
from typing import Any

from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.stat_normalization import stat_key


def find_final_stat(prop: dict) -> dict | None:
    """Look up final stat metadata, including DNP status when available."""
    stored = FinalStatsRepository.find_result(prop)
    if stored is not None:
        return stored

    actual = _find_file_actual_stat(prop)
    if actual is None:
        return None
    return {
        "actual": actual,
        "status": "played",
        "source": "file",
        "game": prop.get("game", ""),
        "game_date": "",
    }


def find_actual_stat(prop: dict) -> float | None:
    """Look up a final stat value for a prop from stored stats or an optional file."""
    result = find_final_stat(prop)
    if result is None or result.get("status") != "played":
        return None
    return result.get("actual")


def _find_file_actual_stat(prop: dict) -> float | None:
    stats = _load_stats()
    if not stats:
        return None

    player = _norm(prop.get("player", ""))
    sport = _norm(prop.get("sport", ""))
    stat = stat_key(prop.get("stat", ""))
    game = _norm(prop.get("game", ""))

    for row in stats:
        if _norm(row.get("player", "")) != player:
            continue
        if sport and _norm(row.get("sport", "")) not in {"", sport}:
            continue
        if stat and stat_key(row.get("stat", "")) != stat:
            continue
        if game and _norm(row.get("game", "")) not in {"", game}:
            continue
        try:
            return float(row["actual"])
        except (KeyError, TypeError, ValueError):
            return None

    return None


def import_final_stats(payload: str, source: str = "manual") -> int:
    rows = parse_final_stats(payload, source=source)
    saved = FinalStatsRepository.upsert_many(rows)
    _load_stats.cache_clear()
    return saved


def parse_final_stats(payload: str, source: str = "manual") -> list[dict[str, Any]]:
    text = payload.strip()
    if not text:
        return []
    if text.startswith("{") or text.startswith("["):
        parsed = json.loads(text)
        rows = parsed.get("stats", []) if isinstance(parsed, dict) else parsed
        return [_with_source(row, source) for row in rows if isinstance(row, dict)]

    reader = csv.DictReader(StringIO(text))
    return [_with_source(dict(row), source) for row in reader]


@lru_cache(maxsize=1)
def _load_stats() -> list[dict[str, Any]]:
    path = os.getenv("EDGEIQ_FINAL_STATS_FILE", "").strip()
    if not path:
        return []

    source = Path(path)
    if not source.exists():
        return []

    with source.open("r", encoding="utf-8") as handle:
        return parse_final_stats(handle.read(), source="file")


def _with_source(row: dict[str, Any], source: str) -> dict[str, Any]:
    return {**row, "source": row.get("source") or source}


def _norm(value: object) -> str:
    return str(value or "").strip().lower()

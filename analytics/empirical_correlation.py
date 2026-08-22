from __future__ import annotations

import math
import time

from utils.entity_normalization import canonical_matchup_key
from utils.stat_normalization import canonical_stat_label

_cache: tuple[float, dict[tuple, dict]] = (0.0, {})


def empirical_pair_correlation(first, second, minimum_pairs: int = 8) -> dict | None:
    segments = _learned_segments()
    key = _segment_key(first, second)
    learned = segments.get(key)
    if not learned or learned["samples"] < minimum_pairs:
        return None
    return learned


def _learned_segments() -> dict[tuple, dict]:
    global _cache
    now = time.monotonic()
    if _cache[0] > now:
        return _cache[1]
    from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository

    rows = [row for row in PredictionLedgerRepository.evidence_rows() if row.get("result") in {"Win", "Loss"}]
    by_entry: dict[int, list[dict]] = {}
    for row in rows:
        by_entry.setdefault(int(row.get("entry_id") or 0), []).append(row)
    observations: dict[tuple, list[tuple[int, int]]] = {}
    for entry_rows in by_entry.values():
        for left in range(len(entry_rows)):
            for right in range(left + 1, len(entry_rows)):
                first, second = entry_rows[left], entry_rows[right]
                observations.setdefault(_segment_key(first, second), []).append(
                    (int(first["result"] == "Win"), int(second["result"] == "Win"))
                )
    learned = {
        key: {"correlation": round(value, 3), "samples": len(pairs), "source": "settled_paired_props"}
        for key, pairs in observations.items()
        if (value := _phi(pairs)) is not None
    }
    _cache = (now + 300.0, learned)
    return learned


def _segment_key(first, second) -> tuple:
    sport = str(_value(first, "sport") or _sport(first)).upper()
    stats = tuple(sorted((canonical_stat_label(_value(first, "stat")), canonical_stat_label(_value(second, "stat")))))
    first_game = canonical_matchup_key(_value(first, "game"))
    same_game = bool(first_game and first_game == canonical_matchup_key(_value(second, "game")))
    same_team = bool(_team(first) and _team(first) == _team(second))
    directions = "same" if str(_value(first, "direction")).lower() == str(_value(second, "direction")).lower() else "opposite"
    return sport, stats, same_game, same_team, directions


def _phi(pairs: list[tuple[int, int]]) -> float | None:
    n11 = sum(left and right for left, right in pairs)
    n10 = sum(left and not right for left, right in pairs)
    n01 = sum(not left and right for left, right in pairs)
    n00 = len(pairs) - n11 - n10 - n01
    denominator = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    return ((n11 * n00) - (n10 * n01)) / denominator if denominator else None


def _value(prop, name: str):
    return prop.get(name, "") if isinstance(prop, dict) else getattr(prop, name, "")


def _team(prop) -> str:
    return str(prop.get("team") or "") if isinstance(prop, dict) else str(getattr(getattr(prop, "player", None), "team", "") or "")


def _sport(prop) -> str:
    return str(prop.get("sport") or "") if isinstance(prop, dict) else str(getattr(getattr(prop, "player", None), "sport", "") or "")

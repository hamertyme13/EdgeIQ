from __future__ import annotations

from repository.repositories.entry_repository import EntryRepository
from utils.stat_normalization import stat_key


def feedback_adjustment(confidence: float, prop: object | None = None) -> float:
    entries = [
        entry for entry in EntryRepository.all()
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss"}
    ]
    if len(entries) < 5:
        return 0.0

    band_floor = int(confidence // 10) * 10
    sample = _segment_prop_sample(entries, prop, band_floor)
    if len(sample) < 3:
        sample = [
            {"confidence": float(entry.get("average_confidence", 0)), "result": entry["result"]}
            for entry in entries
            if int(float(entry.get("average_confidence", 0)) // 10) * 10 == band_floor
        ]
    if len(sample) < 3:
        sample = [
            {"confidence": float(entry.get("average_confidence", 0)), "result": entry["result"]}
            for entry in entries
        ]

    actual = sum(1 for row in sample if row["result"] == "Win") / len(sample) * 100
    predicted = sum(float(row.get("confidence") or 0) for row in sample) / len(sample)
    return round(max(-8.0, min(8.0, (actual - predicted) * 0.25)), 2)


def _segment_prop_sample(entries: list[dict], prop: object | None, band_floor: int) -> list[dict]:
    if prop is None:
        return []

    target = _prop_segments(prop)
    rows: list[dict] = []
    for entry in entries:
        for row in entry.get("props") or []:
            result = row.get("final_result") or row.get("result") or ""
            confidence = row.get("confidence")
            if result not in {"Win", "Loss"} or confidence in (None, ""):
                continue
            if int(float(confidence) // 10) * 10 != band_floor:
                continue
            segments = _row_segments(row)
            match_score = sum(1 for key in ("sport", "stat", "platform", "direction") if target.get(key) and target.get(key) == segments.get(key))
            if match_score >= 2:
                rows.append({"confidence": float(confidence), "result": result, "match_score": match_score})

    rows.sort(key=lambda row: row["match_score"], reverse=True)
    return rows


def _prop_segments(prop: object) -> dict:
    player = getattr(prop, "player", None)
    stat = getattr(prop, "stat", "")
    platform = getattr(prop, "platform", "")
    return {
        "sport": str(getattr(player, "sport", "") or "").upper(),
        "stat": stat_key(getattr(stat, "value", stat)),
        "platform": str(getattr(platform, "value", platform) or "").lower(),
        "direction": str(getattr(prop, "direction", "") or "").lower(),
    }


def _row_segments(row: dict) -> dict:
    return {
        "sport": str(row.get("sport", "") or "").upper(),
        "stat": stat_key(row.get("stat", "")),
        "platform": str(row.get("platform", "") or "").lower(),
        "direction": str(row.get("direction", "") or "").lower(),
    }

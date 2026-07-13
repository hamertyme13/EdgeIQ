from __future__ import annotations

from repository.repositories.entry_repository import EntryRepository


def feedback_adjustment(confidence: float) -> float:
    entries = [
        entry for entry in EntryRepository.all()
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss"}
    ]
    if len(entries) < 5:
        return 0.0

    band_floor = int(confidence // 10) * 10
    band = [
        entry for entry in entries
        if int(float(entry.get("average_confidence", 0)) // 10) * 10 == band_floor
    ]
    sample = band if len(band) >= 3 else entries
    actual = sum(1 for entry in sample if entry["result"] == "Win") / len(sample) * 100
    predicted = sum(float(entry.get("average_confidence", 0)) for entry in sample) / len(sample)
    return round(max(-8.0, min(8.0, (actual - predicted) * 0.25)), 2)

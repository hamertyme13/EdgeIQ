"""Descriptive personal results from verified settled ledger placements."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite

from sqlalchemy import func

from analytics.linked_offer_evaluation import VERIFIED_FINAL_SOURCES
from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from utils.stat_normalization import canonical_stat_label

MAX_PLACEMENTS = 5000
MIN_INSIGHT_DECISIONS = 30


def _verified_decision(row: dict) -> tuple[str | None, str]:
    if str(row.get("final_source") or "").lower() not in VERIFIED_FINAL_SOURCES:
        return None, "unverified_source"
    if str(row.get("final_status") or "").lower() != "played":
        return None, "not_final"
    result = str(row.get("final_result") or "")
    direction = str(row.get("direction") or "").title()
    if result not in {"Win", "Loss"} or direction not in {"Over", "Under"}:
        return None, "no_win_loss_decision"
    try:
        actual, line = float(row["actual"]), float(row["line"])
    except (KeyError, TypeError, ValueError):
        return None, "missing_final_or_line"
    if not isfinite(actual) or not isfinite(line) or actual == line:
        return None, "invalid_or_push_result"
    expected = "Win" if ((actual > line) == (direction == "Over")) else "Loss"
    if result != expected:
        return None, "result_conflict"
    return result, ""


def _confidence_bucket(value: object) -> str:
    try:
        confidence = float(str(value))
    except (TypeError, ValueError):
        return "Unavailable"
    if not isfinite(confidence) or not 0 <= confidence <= 100:
        return "Unavailable"
    if confidence < 50:
        return "0-49%"
    low = min(90, int(confidence // 10) * 10)
    return f"{low}-{low + 9}%" if low < 90 else "90-100%"


def _segments(rows: list[tuple[str, str]]) -> list[dict]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for name, result in rows:
        grouped[name or "Unknown"][result] += 1
    output = []
    for name, counts in grouped.items():
        wins, losses = counts["Win"], counts["Loss"]
        decisions = wins + losses
        output.append({
            "name": name, "wins": wins, "losses": losses, "decisions": decisions,
            "hit_rate": round(100 * wins / decisions, 1),
            "small_sample": decisions < MIN_INSIGHT_DECISIONS,
        })
    return sorted(output, key=lambda item: (-item["decisions"], item["name"]))


def _card_segments(entries: dict[int, dict], *, mode: str) -> tuple[list[dict], list[dict]]:
    by_size: dict[str, list[dict]] = defaultdict(list)
    by_grade: dict[str, list[dict]] = defaultdict(list)
    for entry in entries.values():
        if entry["entry_result"] not in {"Win", "Loss"}:
            continue
        by_size[f"{entry['entry_size']}-leg"].append(entry)
        by_grade[str(entry.get("grade") or "Ungraded")].append(entry)

    def summarize(groups: dict[str, list[dict]]) -> list[dict]:
        output = []
        for name, cards in groups.items():
            wins = sum(card["entry_result"] == "Win" for card in cards)
            decisions = len(cards)
            metric = {
                "name": name, "wins": wins, "losses": decisions - wins,
                "decisions": decisions, "win_rate": round(100 * wins / decisions, 1),
                "small_sample": decisions < MIN_INSIGHT_DECISIONS,
                "max_drawdown": None,
            }
            if mode == "real":
                ordered = sorted((card for card in cards if card.get("settled_at")), key=lambda card: card["settled_at"])
                cumulative = peak = max_drawdown = 0.0
                for card in ordered:
                    cumulative += float(card.get("profit") or 0.0)
                    peak = max(peak, cumulative)
                    max_drawdown = max(max_drawdown, peak - cumulative)
                metric["max_drawdown"] = round(max_drawdown, 2) if ordered else None
            output.append(metric)
        return sorted(output, key=lambda item: (-item["decisions"], item["name"]))

    return summarize(by_size), summarize(by_grade)


def summarize_personal_edge(rows: list[dict], *, mode: str, truncated: bool = False) -> dict:
    if mode not in {"real", "paper"}:
        raise ValueError("Choose paid or paper entries.")
    entries: dict[int, dict] = {}
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    excluded: Counter = Counter()
    wins = losses = 0
    for row in rows:
        entry_id = int(row["entry_id"])
        entries.setdefault(entry_id, row)
        result, reason = _verified_decision(row)
        if result is None:
            excluded[reason] += 1
            continue
        wins += result == "Win"
        losses += result == "Loss"
        for dimension, name in (
            ("sport", str(row.get("sport") or "Unknown").upper()),
            ("stat", canonical_stat_label(row.get("stat") or "Unknown")),
            ("provider", str(row.get("platform") or "Unknown")),
            ("direction", str(row.get("direction") or "Unknown").title()),
            ("confidence_bucket", _confidence_bucket(row.get("confidence"))),
        ):
            groups[dimension].append((name, result))
    segments = {dimension: _segments(groups[dimension]) for dimension in
                ("sport", "stat", "provider", "direction", "confidence_bucket")}
    card_size, grade = _card_segments(entries, mode=mode)
    eligible = [
        {"dimension": dimension, **segment}
        for dimension in ("sport", "stat", "provider")
        for segment in segments[dimension]
        if not segment["small_sample"]
    ]
    strongest = max(eligible, key=lambda item: (item["hit_rate"], item["decisions"])) if eligible and not truncated else None
    weakest = min(eligible, key=lambda item: (item["hit_rate"], -item["decisions"])) if eligible and not truncated else None
    return {
        "mode": mode,
        "summary": {
            "settled_entries": len(entries), "verified_leg_decisions": wins + losses,
            "leg_wins": wins, "leg_losses": losses,
            "leg_hit_rate": round(100 * wins / (wins + losses), 1) if wins + losses else None,
            "excluded_legs": sum(excluded.values()), "excluded_by_reason": dict(excluded),
        },
        "segments": segments, "card_size": card_size, "grade": grade,
        "strongest": strongest, "weakest": weakest, "truncated": truncated,
        "sample_threshold": MIN_INSIGHT_DECISIONS,
        "limitations": [
            "Leg counts represent tracked placements, not independent games. Repeated legs on multiple cards are counted more than once.",
            "Only official-source, line-consistent final Win/Loss legs appear in prop segments. Manual and estimated results are excluded.",
            "Card-size and grade records include manually settled cards; they are separate from verified leg outcomes.",
            "Historical associations do not establish causation or predict future profit.",
        ],
    }


def personal_edge_payload(mode: str = "real") -> dict:
    if mode not in {"real", "paper"}:
        raise ValueError("Choose paid or paper entries.")
    columns = (
        EntryModel.id.label("entry_id"), EntryModel.result.label("entry_result"),
        EntryModel.grade, EntryModel.profit, EntryModel.settled_at,
        func.count(EntryPropModel.id).over(partition_by=EntryModel.id).label("entry_size"),
        EntryPropModel.id.label("entry_prop_id"), EntryPropModel.sport,
        EntryPropModel.stat, EntryPropModel.platform, EntryPropModel.direction,
        EntryPropModel.confidence, EntryPropModel.line, EntryPropModel.actual,
        EntryPropModel.final_status, EntryPropModel.final_source, EntryPropModel.final_result,
    )
    with SessionLocal() as session:
        query = (session.query(*columns)
                 .join(EntryPropModel, EntryPropModel.entry_id == EntryModel.id)
                 .filter(EntryModel.status == "Settled", EntryModel.entry_mode == mode)
                 .order_by(EntryModel.settled_at.desc(), EntryModel.id.desc(), EntryPropModel.id.asc()))
        records = query.limit(MAX_PLACEMENTS + 1).all()
    selected = [dict(record._mapping) for record in records[:MAX_PLACEMENTS]]
    if len(records) > MAX_PLACEMENTS and selected:
        cutoff_entry = selected[-1]["entry_id"]
        selected = [row for row in selected if row["entry_id"] != cutoff_entry]
    return summarize_personal_edge(
        selected,
        mode=mode,
        truncated=len(records) > MAX_PLACEMENTS,
    )

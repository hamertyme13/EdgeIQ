from __future__ import annotations

from analytics.calibration import calibrate
from models.bet import Bet


def backtest_summary(bets: list[Bet], entries: list[dict]) -> dict:
    settled_entries = [
        entry for entry in entries
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push"}
    ]
    graded = _group_entries_by_grade(settled_entries)
    confidence = _entry_confidence_summary(settled_entries)
    bet_summary = _bet_summary(bets)
    calibration_rows = _calibration_rows(bets, settled_entries)

    return {
        "bets": bet_summary,
        "entries": {
            "count": len(settled_entries),
            "wins": sum(1 for entry in settled_entries if entry["result"] == "Win"),
            "losses": sum(1 for entry in settled_entries if entry["result"] == "Loss"),
            "pushes": sum(1 for entry in settled_entries if entry["result"] == "Push"),
            "profit": round(sum(entry.get("profit", 0.0) for entry in settled_entries), 2),
            "wagered": round(sum(entry.get("wager", 0.0) for entry in settled_entries), 2),
            "roi": _entry_roi(settled_entries),
            "by_grade": graded,
            "by_result": _group_entries_by_result(settled_entries),
            "confidence": confidence,
        },
        "calibration": calibration_rows,
    }


def _bet_summary(bets: list[Bet]) -> dict:
    graded = [bet for bet in bets if bet.result in {"Win", "Loss", "Push"}]
    wins = sum(1 for bet in graded if bet.result == "Win")
    losses = sum(1 for bet in graded if bet.result == "Loss")
    pushes = sum(1 for bet in graded if bet.result == "Push")
    wagered = sum(bet.wager for bet in graded)
    profit = sum(bet.profit for bet in graded)
    return {
        "count": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / (wins + losses) * 100, 1) if wins + losses else 0.0,
        "profit": round(profit, 2),
        "wagered": round(wagered, 2),
        "roi": round(profit / wagered * 100, 2) if wagered else 0.0,
    }


def _group_entries_by_grade(entries: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for entry in entries:
        grade = entry.get("grade") or "Ungraded"
        group = groups.setdefault(grade, {"entries": 0, "wins": 0, "losses": 0, "pushes": 0})
        group["entries"] += 1
        if entry["result"] == "Win":
            group["wins"] += 1
        elif entry["result"] == "Loss":
            group["losses"] += 1
        else:
            group["pushes"] += 1

    for group in groups.values():
        decisions = group["wins"] + group["losses"]
        group["win_rate"] = round(group["wins"] / decisions * 100, 1) if decisions else 0.0
    return groups


def _group_entries_by_result(entries: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for entry in entries:
        result = entry.get("result") or "Unknown"
        group = groups.setdefault(result, {"entries": 0, "profit": 0.0, "wagered": 0.0})
        group["entries"] += 1
        group["profit"] += entry.get("profit", 0.0)
        group["wagered"] += entry.get("wager", 0.0)

    for group in groups.values():
        group["profit"] = round(group["profit"], 2)
        group["wagered"] = round(group["wagered"], 2)
        group["roi"] = round((group["profit"] / group["wagered"] * 100) if group["wagered"] else 0.0, 2)
    return groups


def _entry_roi(entries: list[dict]) -> float:
    wagered = sum(entry.get("wager", 0.0) for entry in entries)
    profit = sum(entry.get("profit", 0.0) for entry in entries)
    return round((profit / wagered * 100) if wagered else 0.0, 2)


def _entry_confidence_summary(entries: list[dict]) -> dict:
    decisions = [entry for entry in entries if entry["result"] in {"Win", "Loss"}]
    if not decisions:
        return {"average_confidence": 0.0, "actual_win_rate": 0.0, "edge": 0.0}
    avg_conf = sum(entry.get("average_confidence", 0.0) for entry in decisions) / len(decisions)
    actual = sum(1 for entry in decisions if entry["result"] == "Win") / len(decisions) * 100
    return {
        "average_confidence": round(avg_conf, 1),
        "actual_win_rate": round(actual, 1),
        "edge": round(actual - avg_conf, 1),
    }


def _calibration_rows(bets: list[Bet], entries: list[dict]) -> list[dict]:
    rows = [
        {"win_probability": bet.win_probability, "result": bet.result}
        for bet in bets
        if bet.win_probability
    ]
    rows.extend(
        {"win_probability": entry.get("average_confidence", 0.0), "result": entry.get("result", "")}
        for entry in entries
        if entry.get("status") == "Settled"
    )
    return [
        {
            "label": bucket.label,
            "predicted_low": bucket.predicted_low,
            "predicted_high": bucket.predicted_high,
            "bets": bucket.bets,
            "wins": bucket.wins,
            "actual_pct": round(bucket.actual_pct, 1),
            "predicted_mid": bucket.predicted_mid,
            "error": round(bucket.error, 1),
        }
        for bucket in calibrate(rows)
    ]

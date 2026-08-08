from __future__ import annotations

from collections.abc import Callable

from web.schemas import BetPayload


def personal_profile_payload(*, dashboard: Callable[[], dict]) -> dict:
    dashboard_stats = dashboard()
    entry_stats = dashboard_stats.get("entries", {})
    by_sport = dashboard_stats.get("by_sport", {})
    by_platform = dashboard_stats.get("by_platform", {})
    by_stat = dashboard_stats.get("by_stat", {})
    paper = entry_stats.get("paper", {})
    best_sport = _best_group(by_sport)
    best_platform = _best_group(by_platform)
    weak_spot = _worst_group(by_sport)
    return {
        "summary": {
            "record": dashboard_stats.get("record", "0-0"),
            "profit": dashboard_stats.get("profit", 0.0),
            "roi": dashboard_stats.get("roi", 0.0),
            "recommendation_accuracy": dashboard_stats.get("recommendation_accuracy", {}),
            "paper_calibration": paper,
        },
        "strengths": [
            f"{best_sport['name']} is your strongest sport by profit/ROI."
            if best_sport
            else "Settle more entries to identify strongest sport.",
            (
                f"{best_platform['name']} is your best platform so far."
                if best_platform and float(best_platform.get("profit", 0.0)) > 0
                else "No platform is profitable yet; keep platform comparisons in paper or conservative mode."
                if best_platform
                else "Track platform on each entry to find the best app for you."
            ),
        ],
        "weaknesses": [
            f"{weak_spot['name']} is lagging; consider paper-only until calibration improves."
            if weak_spot
            else "No weak segment detected yet.",
        ],
        "by_sport": by_sport,
        "by_platform": by_platform,
        "by_stat": by_stat,
        "recommended_settings": _recommended_user_settings(dashboard_stats, paper),
    }


def bets_payload(
    limit: int,
    entry_limit: int,
    *,
    load_bets: Callable[[], list],
    load_entries: Callable[[], list[dict]],
    serialize_bet: Callable[[object], dict],
    serialize_entry: Callable[[dict], dict],
) -> dict:
    bounded_limit = max(1, min(limit, 250))
    bounded_entry_limit = max(1, min(entry_limit, 100))
    all_bets = load_bets()
    all_entries = [serialize_entry(entry) for entry in load_entries() if entry.get("status") == "Settled"]
    return {
        "bets": [serialize_bet(bet) for bet in all_bets[:bounded_limit]],
        "entries": all_entries[:bounded_entry_limit],
        "summary": {
            "saved_bets": len(all_bets),
            "completed_entries": len(all_entries),
            "displayed_bets": min(len(all_bets), bounded_limit),
            "displayed_entries": min(len(all_entries), bounded_entry_limit),
        },
    }


def save_bet_payload(
    payload: BetPayload,
    *,
    potential_profit: Callable[[int, float], float],
    create_bet: Callable[[BetPayload, float], object],
    save_bet: Callable[[object], object],
    serialize_bet: Callable[[object], dict],
    dashboard: Callable[[], dict],
) -> dict:
    profit = 0.0
    if payload.result == "Win":
        profit = potential_profit(payload.odds, payload.wager)
    elif payload.result == "Loss":
        profit = -payload.wager
    bet = create_bet(payload, round(profit, 2))
    save_bet(bet)
    return {"bet": serialize_bet(bet), "dashboard": dashboard()}


def _best_group(groups: dict) -> dict | None:
    if not groups:
        return None
    name, stats = max(
        groups.items(),
        key=lambda item: (
            float(item[1].get("profit", 0.0)),
            float(item[1].get("roi", 0.0)),
            int(item[1].get("wins", 0)),
        ),
    )
    return {"name": name, **stats}


def _worst_group(groups: dict) -> dict | None:
    candidates = [
        (name, stats) for name, stats in groups.items() if int(stats.get("wins", 0)) + int(stats.get("losses", 0)) > 0
    ]
    if not candidates:
        return None
    name, stats = min(
        candidates,
        key=lambda item: (
            float(item[1].get("profit", 0.0)),
            float(item[1].get("roi", 0.0)),
        ),
    )
    return {"name": name, **stats}


def _recommended_user_settings(stats: dict, paper: dict) -> dict:
    roi = float(stats.get("roi") or 0.0)
    accuracy = float((stats.get("recommendation_accuracy") or {}).get("accuracy") or 0.0)
    paper_edge = float(paper.get("calibration_edge") or 0.0)
    if roi < 0 or (accuracy and accuracy < 48):
        risk_style = "conservative"
        max_wager_pct = 2.0
    elif roi > 20 and accuracy >= 55 and paper_edge >= -8:
        risk_style = "aggressive"
        max_wager_pct = 7.5
    else:
        risk_style = "balanced"
        max_wager_pct = 5.0
    return {
        "risk_style": risk_style,
        "max_wager_pct": max_wager_pct,
        "paper_first": paper.get("decisions", 0) < 10,
        "note": "Uses your real and paper results to suggest sizing discipline.",
    }

from config import STARTING_BANKROLL
from repository.bet_repository import BetRepository
from repository.repositories.bankroll_transaction_repository import BankrollTransactionRepository
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.settings_repository import SettingsRepository


def get_starting_bankroll() -> float:
    """Read bankroll from DB, falling back to config/env default."""
    stored = SettingsRepository.get("starting_bankroll")
    if stored:
        try:
            return float(stored)
        except ValueError:
            pass
    return STARTING_BANKROLL


def set_starting_bankroll(amount: float) -> None:
    SettingsRepository.set("starting_bankroll", str(amount))


def get_dashboard(starting_bankroll: float | None = None) -> dict:

    if starting_bankroll is None:
        starting_bankroll = get_starting_bankroll()

    stats = BetRepository().dashboard_stats()
    entry_stats = EntryRepository.financial_stats()
    bankroll_transactions = BankrollTransactionRepository.summary()

    stats["wins"] += entry_stats["wins"]
    stats["losses"] += entry_stats["losses"]
    stats["pushes"] += entry_stats["pushes"]
    stats["profit"] = round(stats["profit"] + entry_stats["profit"], 2)
    stats["wagered"] = round(stats["wagered"] + entry_stats["wagered"], 2)
    stats["roi"] = round((stats["profit"] / stats["wagered"] * 100) if stats["wagered"] else 0.0, 2)
    stats["pending_entry_exposure"] = entry_stats["pending_exposure"]
    stats["entries"] = entry_stats
    stats["paper"] = entry_stats.get("paper", {})
    stats["recommendation_accuracy"] = entry_stats.get("recommendation_accuracy", {})
    stats["by_sport"] = _merge_performance_groups(
        stats.get("by_sport", {}),
        entry_stats.get("by_sport", {}),
    )
    stats["by_stat"] = _merge_performance_groups(
        stats.get("by_stat", {}),
        entry_stats.get("by_stat", {}),
    )
    stats["by_platform"] = _merge_performance_groups(
        stats.get("by_platform", {}),
        entry_stats.get("by_platform", {}),
    )
    stats["entry_platform_profitability"] = entry_stats.get("platform_profitability", [])
    stats["bankroll_transactions"] = bankroll_transactions
    stats["performance_insights"] = _performance_insights(stats)

    current_bankroll = (
       starting_bankroll
       + bankroll_transactions["net"]
       + stats["profit"]
       - entry_stats["pending_exposure"]
   )

    stats["bankroll"] = current_bankroll
    stats["record"] = (
          f"{stats['wins']}-{stats['losses']}"
    )
    stats["starting_bankroll"] = starting_bankroll

    return stats


def _merge_performance_groups(bet_groups: dict, entry_groups: dict) -> dict:
    merged: dict[str, dict] = {}
    for source, count_key in ((bet_groups, "bets"), (entry_groups, "entries")):
        for platform, stats in (source or {}).items():
            group = merged.setdefault(
                platform,
                {"bets": 0, "entries": 0, "wins": 0, "losses": 0, "pushes": 0, "profit": 0.0, "wagered": 0.0},
            )
            group[count_key] += stats.get(count_key, stats.get("bets", stats.get("entries", 0)))
            group["wins"] += stats.get("wins", 0)
            group["losses"] += stats.get("losses", 0)
            group["pushes"] += stats.get("pushes", 0)
            group["profit"] += stats.get("profit", 0.0)
            group["wagered"] += stats.get("wagered", 0.0)

    for group in merged.values():
        decisions = group["wins"] + group["losses"]
        group["profit"] = round(group["profit"], 2)
        group["wagered"] = round(group["wagered"], 2)
        group["roi"] = round((group["profit"] / group["wagered"] * 100) if group["wagered"] else 0.0, 2)
        group["win_pct"] = round((group["wins"] / decisions * 100) if decisions else 0.0, 1)
    return dict(sorted(merged.items(), key=lambda item: item[1]["profit"], reverse=True))


def _performance_insights(stats: dict) -> list[dict]:
    insights = []
    sport_rows = _rank_group(stats.get("by_sport", {}))
    platform_rows = _rank_group(stats.get("by_platform", {}))
    stat_rows = _rank_group(stats.get("by_stat", {}))

    best_sport = _first_with_decisions(sport_rows)
    worst_sport = _last_with_decisions(sport_rows)
    best_platform = _first_with_decisions(platform_rows)
    weakest_stat = _last_with_decisions(stat_rows)

    if best_sport:
        insights.append({
            "title": f"Lean into {best_sport['name']}",
            "summary": (
                f"{best_sport['name']} is your strongest sport: "
                f"{best_sport['win_pct']}% win rate, {best_sport['profit']:+.2f} profit, {best_sport['decisions']} decisions."
            ),
            "tone": "positive" if best_sport["profit"] >= 0 else "neutral",
        })
    if worst_sport and (not best_sport or worst_sport["name"] != best_sport["name"]):
        insights.append({
            "title": f"Tighten {worst_sport['name']} filters",
            "summary": (
                f"{worst_sport['name']} is lagging: {worst_sport['win_pct']}% win rate and "
                f"{worst_sport['profit']:+.2f} profit. Raise confidence or edge minimums there."
            ),
            "tone": "warning",
        })
    if best_platform:
        insights.append({
            "title": f"Best platform: {best_platform['name']}",
            "summary": (
                f"{best_platform['name']} leads platform profitability with "
                f"{best_platform['profit']:+.2f} profit and {best_platform['roi']}% ROI."
            ),
            "tone": "positive" if best_platform["profit"] >= 0 else "neutral",
        })
    if weakest_stat:
        insights.append({
            "title": f"Review {weakest_stat['name']} props",
            "summary": (
                f"{weakest_stat['name']} has {weakest_stat['win_pct']}% win rate. "
                "Use this to prune markets where the model has not proven itself yet."
            ),
            "tone": "warning" if weakest_stat["win_pct"] < 50 else "neutral",
        })

    if not insights:
        insights.append({
            "title": "Build your sample",
            "summary": "Settle more entries and import history to unlock sharper sport, platform, and stat recommendations.",
            "tone": "neutral",
        })
    return insights[:4]


def _rank_group(group: dict) -> list[dict]:
    rows = []
    for name, stats in (group or {}).items():
        decisions = stats.get("wins", 0) + stats.get("losses", 0)
        rows.append({"name": name, "decisions": decisions, **stats})
    rows.sort(key=lambda row: (row.get("profit", 0.0), row.get("win_pct", 0.0), row["decisions"]), reverse=True)
    return rows


def _first_with_decisions(rows: list[dict]) -> dict | None:
    return next((row for row in rows if row.get("decisions", 0) > 0), None)


def _last_with_decisions(rows: list[dict]) -> dict | None:
    candidates = [row for row in rows if row.get("decisions", 0) > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row.get("profit", 0.0), row.get("win_pct", 0.0)))
    return candidates[0]

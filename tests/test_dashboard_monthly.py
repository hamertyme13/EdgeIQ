from datetime import UTC, datetime

from models.bet import Bet
from services.dashboard import _month_key, monthly_dashboard_performance, monthly_profit_log


def _entry(result, when, *, mode="real", recommended=False, status="Settled"):
    return {
        "status": status,
        "result": result,
        "entry_mode": mode,
        "recommended_by_app": recommended,
        "wager": 10.0 if mode == "real" else 0.0,
        "profit": 20.0 if result == "Win" and mode == "real" else -10.0 if result == "Loss" and mode == "real" else 0.0,
        "settled_at": when if status == "Settled" else None,
        "placed_at": when,
        "platform": "PrizePicks",
        "props": [],
    }


def test_today_performance_resets_on_month_boundary_without_losing_history():
    september = datetime(2026, 9, 30, 23, 0, tzinfo=UTC)
    october = datetime(2026, 10, 1, 5, 0, tzinfo=UTC)
    bets = [
        Bet("WNBA", "A-B", "A points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 65, created_at=september),
    ]
    entries = [
        _entry("Win", september, recommended=True),
        _entry("Loss", october, recommended=True),
        _entry("Win", october, mode="paper"),
        _entry(None, october, status="Pending", recommended=True),
    ]

    current = monthly_dashboard_performance(bets, entries, "2026-10")
    previous = monthly_dashboard_performance(bets, entries, "2026-09")

    assert current["record"] == "0-1"
    assert current["profit"] == -10.0
    assert current["roi"] == -100.0
    assert current["current_streak"] == -1
    assert current["recommendation_accuracy"]["pending"] == 1
    assert current["recommendation_accuracy"]["accuracy"] == 0.0
    assert current["paper"]["accuracy"] == 100.0
    assert previous["record"] == "2-0"
    assert previous["recommendation_accuracy"]["accuracy"] == 100.0


def test_month_rollover_uses_eastern_calendar_day():
    assert _month_key("2026-10-01T01:00:00Z") == "2026-09"
    assert _month_key("2026-10-01T05:00:00Z") == "2026-10"
    assert _month_key(None) == ""
    assert _month_key("date unavailable") == ""


def test_undated_legacy_outcome_does_not_pollute_current_month():
    undated = Bet("WNBA", "A-B", "A points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 65)

    assert monthly_dashboard_performance([undated], [], "2026-10")["record"] == "0-0"
    assert monthly_profit_log([undated], [])["months"] == []


def test_paper_bet_does_not_enter_paid_monthly_profit():
    paper = Bet(
        "WNBA", "A-B", "A points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 65,
        entry_mode="paper", created_at=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert monthly_dashboard_performance([paper], [], "2026-10")["record"] == "0-0"
    assert monthly_profit_log([paper], [])["months"] == []

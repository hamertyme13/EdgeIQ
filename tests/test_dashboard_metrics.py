from types import SimpleNamespace

from services.dashboard import _combined_timeline_stats


def test_combined_timeline_includes_settled_real_entries_in_streak_and_drawdown() -> None:
    bets = [
        SimpleNamespace(
            result="Win",
            profit=20.0,
            created_at="2026-08-01T12:00:00Z",
            entry_mode="real",
        ),
    ]
    entries = [
        {
            "status": "Settled",
            "result": "Loss",
            "profit": -10.0,
            "settled_at": "2026-08-02T12:00:00Z",
            "entry_mode": "real",
        },
        {
            "status": "Settled",
            "result": "Loss",
            "profit": -5.0,
            "settled_at": "2026-08-03T12:00:00Z",
            "entry_mode": "real",
        },
    ]

    stats = _combined_timeline_stats(bets, entries)

    assert stats["current_streak"] == -2
    assert stats["best_streak"] == 1
    assert stats["worst_streak"] == -2
    assert stats["max_drawdown"] == 15.0
    assert stats["bankroll_curve"] == [20.0, 10.0, 5.0]


def test_combined_timeline_orders_results_and_excludes_paper_entries() -> None:
    bets = [
        SimpleNamespace(
            result="Loss",
            profit=-10.0,
            created_at="2026-08-03T12:00:00Z",
            entry_mode="real",
        ),
    ]
    entries = [
        {
            "status": "Settled",
            "result": "Win",
            "profit": 10.0,
            "settled_at": "2026-08-01T12:00:00Z",
            "entry_mode": "real",
        },
        {
            "status": "Settled",
            "result": "Win",
            "profit": 100.0,
            "settled_at": "2026-08-04T12:00:00Z",
            "entry_mode": "paper",
        },
    ]

    stats = _combined_timeline_stats(bets, entries)

    assert stats["current_streak"] == -1
    assert stats["performance_timeline_count"] == 2
    assert stats["max_drawdown"] == 10.0
    assert stats["bankroll_curve"] == [10.0, 0.0]

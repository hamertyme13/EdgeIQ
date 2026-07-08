from datetime import datetime

import web.app as web_app
import data.providers.final_stats as final_stats
import analytics.hit_rate as hit_rate_module
from web.app import (
    EntryPayload,
    EvPayload,
    _check_entry_result,
    _entry_progress_payload,
    _line_movement_payload,
    _trending_games_payload,
    analyze_entry,
    analyze_ev,
    backtest,
    dashboard_parlay,
    entry_progress,
    health,
    import_final_stats_endpoint,
    optimize_entries,
    place_entry,
    player_hit_rate,
    player_detail,
    trending_games,
    top_props,
)
from models.bet import Bet
from web.app import FinalStatsPayload
from repository.repositories.entry_repository import EntryRepository


def test_web_health_endpoint():
    assert health() == {"ok": True}


def test_web_ev_endpoint():
    body = analyze_ev(EvPayload(odds=-110, probability=55))

    assert body["recommendation"]["grade"] == "B"
    assert body["expected_value"] == 5.0


def test_web_entry_analysis_auto_projects_missing_projection():
    body = analyze_entry(
        EntryPayload.model_validate(
            {
            "platform": "PrizePicks",
            "props": [
                {
                    "player": "A",
                    "team": "AAA",
                    "sport": "WNBA",
                    "stat": "Points",
                    "line": 20.5,
                    "trending_count": 100000,
                },
                {
                    "player": "B",
                    "team": "BBB",
                    "sport": "WNBA",
                    "stat": "Assists",
                    "line": 7.5,
                    "trending_count": 90000,
                },
            ],
            }
        )
    )

    props = body["entry"]["props"]
    assert all(prop["auto_projected"] for prop in props)
    assert all(prop["projection"] > prop["line"] for prop in props)


def test_web_top_props_returns_five_per_sport(monkeypatch):
    raw_props = [
        {"player": f"W{i}", "league": "WNBA", "stat": "Points", "line": 10.5, "trending_count": 100 - i}
        for i in range(6)
    ] + [
        {"player": f"M{i}", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 80 - i}
        for i in range(6)
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)

    body = top_props(platform="PrizePicks", sport="All Sports")

    assert len([prop for prop in body["props"] if prop["league"] == "WNBA"]) == 5
    assert len([prop for prop in body["props"] if prop["league"] == "MLB"]) == 5
    assert body["per_sport_limit"] == 5


def test_web_dashboard_parlay_serializes_three_legs(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
    ]
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)

    body = dashboard_parlay(platform="PrizePicks", sport="WNBA")

    assert body["suggestion"]["entry"]["platform"] == "PrizePicks"
    assert len(body["suggestion"]["entry"]["props"]) == 3


def test_place_entry_saves_wager_and_multiplier(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        lambda entry, status="Draft", result="", wager=0.0, multiplier=1.0: saved.setdefault(
            "payload",
            {"status": status, "wager": wager, "multiplier": multiplier},
        ) or 11,
    )
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 90.0})

    body = place_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "wager": 10,
                "multiplier": 3,
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
                ],
            }
        )
    )

    assert body["status"] == "Pending"
    assert saved["payload"] == {"status": "Pending", "wager": 10.0, "multiplier": 3.0}


def test_entry_profit_uses_multiplier_as_net_profit():
    assert EntryRepository._profit_for_result("Win", 10, 3) == 20
    assert EntryRepository._profit_for_result("Loss", 10, 3) == -10
    assert EntryRepository._profit_for_result("Push", 10, 3) == 0


def test_trending_games_payload_highlights_ranked_players():
    props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "game": "SEA-NYL", "trending_count": 100},
        {"player": "B", "team": "BBB", "league": "WNBA", "game": "SEA-NYL", "trending_count": 60},
        {"player": "C", "team": "CCC", "league": "MLB", "game": "LAD-SF", "trending_count": 200},
    ]
    ranked = [
        {"player": "a", "league": "WNBA"},
        {"player": "C", "league": "MLB"},
    ]

    games = _trending_games_payload(props, ranked, limit=5)

    assert games[0]["game"] == "LAD-SF"
    assert games[0]["ranked_players"][0]["player"] == "C"
    assert games[1]["game"] == "SEA-NYL"
    assert games[1]["trending_count"] == 160
    assert games[1]["ranked_players"][0]["player"] == "A"


def test_trending_games_endpoint_uses_top_props_as_ranked_players(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "SEA-NYL", "trending_count": 100},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "game": "SEA-NYL", "trending_count": 90},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "game": "DAL-PHX", "trending_count": 80},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)

    body = trending_games(platform="PrizePicks", sport="WNBA", limit=2)

    assert body["games"][0]["game"] == "SEA-NYL"
    assert body["games"][0]["ranked_player_count"] == 2
    assert body["ranked_player_count"] == 3


def test_web_player_detail_summarizes_active_player_props(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)

    body = player_detail("A", platform="PrizePicks", sport="WNBA")

    assert body["player"] == "A"
    assert body["prop_count"] == 2
    assert body["best_prop"]["player"] == "A"
    assert "line_movement" in body["props"][0]
    assert "hit_rate" in body["props"][0]


def test_line_movement_payload_reports_direction():
    body = _line_movement_payload(
        "A",
        "Points",
        "PrizePicks",
        [
            {"line": 20.5, "recorded_at": datetime(2026, 7, 8, 10, 0)},
            {"line": 22.5, "recorded_at": datetime(2026, 7, 8, 11, 0)},
        ],
    )

    assert body["direction"] == "up"
    assert body["change"] == 2.0


def test_line_movement_payload_can_use_active_line_as_current():
    body = _line_movement_payload(
        "A",
        "Points",
        "PrizePicks",
        [
            {"line": 20.5, "recorded_at": datetime(2026, 7, 8, 10, 0)},
            {"line": 18.5, "recorded_at": datetime(2026, 7, 8, 11, 0)},
        ],
        current_line=21.5,
    )

    assert body["current"] == 21.5
    assert body["previous"] == 18.5
    assert body["direction"] == "up"


def test_web_hit_rate_endpoint_returns_projection_model_buckets():
    body = player_hit_rate("A", stat="Points", line=20.5, projection=23.0)

    assert body["source"] == "projection_model"
    assert body["estimated_hit_rate"] > 50
    assert body["last_5"] >= body["season"]


def test_final_stat_import_endpoint_saves_rows(monkeypatch):
    saved = {}
    monkeypatch.setattr(web_app, "import_final_stats", lambda payload, source: saved.setdefault(source, 2))

    body = import_final_stats_endpoint(FinalStatsPayload(payload="player,sport,stat,actual\nA,WNBA,Points,24", source="test"))

    assert body == {"imported": 2, "source": "test"}
    assert saved == {"test": 2}


def test_hit_rate_uses_final_stat_history(monkeypatch):
    monkeypatch.setattr(
        hit_rate_module.FinalStatsRepository,
        "history",
        lambda player, stat, sport=None, limit=100: [
            {"actual": 24},
            {"actual": 18},
            {"actual": 25},
        ],
    )

    body = player_hit_rate("A", stat="Points", line=20.5, projection=22.0, sport="WNBA")

    assert body["source"] == "final_stats"
    assert body["sample_size"] == 3
    assert body["season"] == 66.7


def test_web_optimizer_ranks_multiple_leg_counts(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "MLB", "stat": "Runs", "line": 0.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "MLB", "stat": "RBIs", "line": 0.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 70000},
    ]
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)

    body = optimize_entries(platform="PrizePicks", sport="MLB", min_legs=2, max_legs=3, limit=3)

    assert [suggestion["rank"] for suggestion in body["suggestions"]] == [1, 2, 3]
    assert {suggestion["leg_count"] for suggestion in body["suggestions"]} <= {2, 3}


def test_web_optimizer_applies_filters(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 100000},
        {"player": "B", "team": "AAA", "league": "MLB", "stat": "Runs", "line": 0.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "MLB", "stat": "RBIs", "line": 0.5, "trending_count": 80000},
    ]
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)

    body = optimize_entries(
        platform="PrizePicks",
        sport="MLB",
        min_legs=2,
        max_legs=2,
        limit=5,
        max_same_team=1,
        apply_feedback=False,
    )

    assert body["suggestions"]
    assert all(
        len({prop["team"] for prop in suggestion["entry"]["props"]}) == 2
        for suggestion in body["suggestions"]
    )


def test_auto_check_result_can_settle_with_projection_estimates(monkeypatch):
    settled = {}
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result: settled.update({entry_id: result}))
    entry = {
        "id": 42,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 23.0},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "projection": 8.5},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=True)

    assert body["settled"] is True
    assert body["result"] == "Win"
    assert body["source"] == "projection_estimate"
    assert settled == {42: "Win"}


def test_auto_check_result_can_settle_with_final_stats_file(monkeypatch, tmp_path):
    stats_file = tmp_path / "final_stats.json"
    stats_file.write_text(
        '{"stats":[{"player":"A","sport":"WNBA","stat":"Points","game":"SEA","actual":24}]}',
        encoding="utf-8",
    )
    final_stats._load_stats.cache_clear()
    monkeypatch.setenv("EDGEIQ_FINAL_STATS_FILE", str(stats_file))
    settled = {}
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result: settled.update({entry_id: result}))
    entry = {
        "id": 7,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 19.0, "game": "SEA"},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is True
    assert body["result"] == "Win"
    assert body["source"] == "actual_provider"
    assert settled == {7: "Win"}
    final_stats._load_stats.cache_clear()


def test_entry_progress_payload_reports_leg_status_from_final_stats(monkeypatch):
    monkeypatch.setattr(web_app, "_actual_stat_for_prop", lambda prop: 24.0)
    entry = {
        "id": 9,
        "platform": "PrizePicks",
        "placed_at": datetime(2026, 7, 8, 12, 0),
        "average_confidence": 65.0,
        "average_edge": 1.5,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 23.0, "game": "SEA"},
        ],
    }

    body = _entry_progress_payload(entry)

    assert body["completed_legs"] == 1
    assert body["projected_result"] == "Win"
    assert body["source"] == "actual_provider"
    assert body["legs"][0]["status"] == "Win"


def test_entry_progress_endpoint_uses_pending_entries(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])

    body = entry_progress()

    assert body == {"entries": [], "active": 0, "with_live_stats": 0}


def test_backtest_endpoint_summarizes_bets_and_entries(monkeypatch):
    bets = [
        Bet("WNBA", "A-B", "A points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 65),
        Bet("WNBA", "C-D", "C assists", -110, 10, "Loss", -10, "PrizePicks", "Assists", 55),
    ]
    entries = [
        {
            "id": 1,
            "status": "Settled",
            "result": "Win",
            "grade": "B",
            "average_confidence": 65.0,
            "wager": 10.0,
            "profit": 20.0,
        },
        {
            "id": 2,
            "status": "Settled",
            "result": "Loss",
            "grade": "C",
            "average_confidence": 55.0,
            "wager": 10.0,
            "profit": -10.0,
        },
    ]
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: bets)
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)

    body = backtest()

    assert body["bets"]["count"] == 2
    assert body["entries"]["count"] == 2
    assert body["entries"]["profit"] == 10.0
    assert body["entries"]["by_result"]["Win"]["profit"] == 20.0
    assert body["entries"]["by_result"]["Loss"]["profit"] == -10.0
    assert body["entries"]["by_grade"]["B"]["win_rate"] == 100.0
    assert body["calibration"]

from datetime import datetime, timedelta
import base64
import json
from types import SimpleNamespace

import web.app as web_app
import services.dashboard as dashboard_service
import data.providers.final_stats as final_stats
import data.providers.espn as espn
import data.providers.nba_summer_league as nba_summer_league
import data.providers.sleeper as sleeper
from data.providers.prop_filters import is_combined_player_prop
from data.providers.generic_props import normalize_props
import analytics.hit_rate as hit_rate_module
from web.app import (
    EntryPayload,
    AutoPaperCalibrationPayload,
    EvPayload,
    ParlayChatPayload,
    PropPayload,
    DnpSettingPayload,
    UploadAnalyzePayload,
    AiEntryReviewPayload,
    BankrollTransactionPayload,
    AlertDeliveryPayload,
    HedgeCalculatorPayload,
    MiddleCalculatorPayload,
    _check_entry_result,
    _calibration_feedback_signals,
    _entry_progress_payload,
    _leg_result,
    _line_movement_payload,
    _parse_parlay_request,
    _parse_betting_history,
    _trending_games_payload,
    analyze_entry,
    auto_paper_calibration,
    analyze_ev,
    backtest,
    backfill_entry_final_stats,
    bets,
    dashboard_command_center,
    dashboard_parlay,
    daily_briefing,
    dnp_setting,
    entry_progress,
    ev_scanner,
    health,
    import_final_stats_endpoint,
    optimize_entries,
    place_entry,
    placement_check,
    player_hit_rate,
    player_detail,
    classify_default_entry_wagers,
    import_betting_history,
    ai_parlay_chat,
    ai_entry_review,
    ai_status,
    entry_suggestions,
    confirmed_props,
    confirmed_entry_suggestions,
    trending_games,
    line_shop,
    market_timing_alerts,
    clv_report,
    hedge_calculator,
    import_wizard,
    run_sync,
    middle_calculator,
    top_props,
    player_research,
    projection_assist,
    refresh_calibration_data,
    recheck_entry_final_stats,
    sharp_consensus,
    update_alert_delivery_settings,
    save_bankroll_transaction,
    update_dnp_setting,
    analyze_uploaded_file,
    model_health,
    _stat_from_text,
)
from models.bet import Bet
from web.app import BettingHistoryPayload, FinalStatsPayload, ProjectionAssistPayload
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.final_stats_repository import _best_matching_row
from repository.bet_repository import BetRepository
from models.stat_type import StatType
from utils.time import iso_utc, utc_now


def test_web_health_endpoint():
    assert health() == {"ok": True}


def test_datetime_serialization_marks_naive_db_values_as_utc():
    assert iso_utc(datetime(2026, 7, 10, 4, 10)) == "2026-07-10T04:10:00+00:00"
    assert iso_utc(utc_now()).endswith("+00:00")


def test_nba_summer_league_game_finder_parses_unique_game_ids(monkeypatch):
    captured = {}

    def fake_get_json(url, **kwargs):
        captured["url"] = url
        return SimpleNamespace(data={
            "resultSets": [{
                "name": "LeagueGameFinderResults",
                "headers": ["GAME_ID", "GAME_DATE", "MATCHUP"],
                "rowSet": [
                    ["0012600001", "2026-07-13", "BOS vs. ATL"],
                    ["0012600001", "2026-07-13", "ATL @ BOS"],
                ],
            }]
        })

    monkeypatch.setattr(nba_summer_league, "get_json", fake_get_json)

    games = nba_summer_league.fetch_summer_league_games(datetime(2026, 7, 13).date())

    assert len(games) == 1
    assert games[0]["GAME_ID"] == "0012600001"
    assert "SeasonType=Summer+League" in captured["url"]
    assert "PlayerOrTeam=T" in captured["url"]


def test_nba_summer_league_box_score_normalizes_player_stats(monkeypatch):
    def fake_get_json(url, **kwargs):
        return SimpleNamespace(data={
            "resultSets": [{
                "name": "PlayerStats",
                "headers": ["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS", "REB", "AST", "STL", "BLK", "TO", "FG3M", "COMMENT", "MIN"],
                "rowSet": [
                    ["Cameron Boozer", "DAL", 22, 8, 3, 1, 2, 4, 2, "", "28:14"],
                ],
            }]
        })

    monkeypatch.setattr(nba_summer_league, "get_json", fake_get_json)

    rows = nba_summer_league.fetch_box_score(
        "0012600002",
        {"GAME_DATE": "2026-07-13", "MATCHUP": "DAL @ MEM"},
    )

    points = next(row for row in rows if row["stat"] == "Points")
    pra = next(row for row in rows if row["stat"] == "PRA")
    threes = next(row for row in rows if row["stat"] == "3-Pointers Made")
    assert points["player"] == "Cameron Boozer"
    assert points["actual"] == 22
    assert points["game"] == "DAL@MEM"
    assert points["source"] == "nba_summer_league"
    assert pra["actual"] == 33
    assert threes["actual"] == 2


def test_combined_player_props_are_filtered_but_pra_is_allowed():
    assert is_combined_player_prop({"player": "A.J. Brown + DeVonta Smith", "stat": "Receiving Yards"})
    assert is_combined_player_prop({"player": "Jalen Brunson and Karl-Anthony Towns", "stat": "Points"})
    assert not is_combined_player_prop({"player": "Paige Bueckers", "stat": "Points + Rebounds + Assists"})


def test_entry_analyze_rejects_combined_player_props():
    payload = EntryPayload(
        entry_mode="paper",
        platform="Underdog",
        props=[
            PropPayload(
                player="A.J. Brown + DeVonta Smith",
                team="PHI",
                sport="NFL",
                stat="Receiving Yards",
                line=90.5,
                projection=92.0,
            )
        ],
    )

    try:
        analyze_entry(payload)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
        assert "Combined-player props" in getattr(exc, "detail", "")
    else:
        raise AssertionError("Combined-player prop was not rejected")


def test_dashboard_command_center_returns_release_cards(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_fetch_props",
        lambda platform, sport: [
            {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA", "trending_count": 100000, "platform": "PrizePicks"},
            {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 6.5, "game": "BBB", "trending_count": 90000, "platform": "PrizePicks"},
            {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "game": "CCC", "trending_count": 80000, "platform": "PrizePicks"},
            {"player": "D", "team": "DDD", "league": "WNBA", "stat": "Points", "line": 14.5, "game": "DDD", "trending_count": 70000, "platform": "PrizePicks"},
            {"player": "E", "team": "EEE", "league": "WNBA", "stat": "Points", "line": 12.5, "game": "EEE", "trending_count": 60000, "platform": "PrizePicks"},
        ],
    )

    body = dashboard_command_center("PrizePicks", "WNBA")

    assert body["cards"]
    assert body["cards"][0]["explanation"]["legs"]
    assert "trust" in body["cards"][0]
    assert "stake" in body["cards"][0]
    assert "no_bet_rule" in body["cards"][0]["explanation"]
    assert body["model_health"]["trust_score"] >= 0


def test_daily_briefing_returns_bet_paper_watch_avoid_sections(monkeypatch):
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": default)
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: None)
    command_card = {
        "type": "entry",
        "title": "Safer Slip",
        "summary": "Lower volatility entry to start with.",
        "score": 76.5,
        "grade": "B",
        "action": "Power Play",
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "direction": "Over", "line": 20.5, "confidence": 64, "edge": 1.2, "platform": "PrizePicks"},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "direction": "Under", "line": 6.5, "confidence": 61, "edge": 0.8, "platform": "PrizePicks"},
        ],
        "suggestion": {"entry": {"props": []}},
        "warnings": [],
        "trust": {"score": 68, "label": "Playable"},
        "timing": {"score": 66, "label": "Good Window"},
        "stake": {"amount": 7.5, "unit_label": "Balanced sizing"},
        "explanation": {"legs": [{"player": "A"}]},
    }
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "bankroll": 100.0,
        "profit": 12.0,
        "roi": 8.0,
        "monthly_profit": {"current_month": {"profit": 10.0, "roi": 5.0}},
        "entries": {"paper": {"pending": 1}},
    })
    monkeypatch.setattr(web_app, "_command_center_payload", lambda platform, sport: {
        "platform": platform,
        "sport": sport or "All Sports",
        "cards": [command_card],
        "avoid": [{"player": "C", "stat": "Rebounds", "direction": "Over", "line": 8.5, "confidence": 45, "edge": -0.5}],
        "model_health": {"trust_score": 64, "status": "Usable"},
    })
    monkeypatch.setattr(web_app, "_model_health_payload", lambda: {
        "trust_score": 72,
        "status": "Usable",
        "paid_entry_mode": "enabled",
        "scorecard": {"score": 72, "sample_size": 30, "roi": 8},
    })
    monkeypatch.setattr(web_app, "_confirmed_props_payload", lambda platform, sport, limit=80: {
        "count": 12,
        "rejected_count": 3,
        "analyzed_count": 15,
        "slate": [{"sport": "WNBA", "games": 2, "props": 12}],
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "direction": "Over", "line": 20.5, "confidence": 64, "edge": 1.2, "platform": "PrizePicks", "game": "AAA-BBB", "trending_count": 1000},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "direction": "Under", "line": 6.5, "confidence": 61, "edge": 0.8, "platform": "PrizePicks", "game": "AAA-BBB", "trending_count": 900},
        ],
        "raw_props": [],
    })
    monkeypatch.setattr(web_app, "_daily_paper_cards", lambda platform, sport, stats: [{
        "type": "paper",
        "title": "Paper Calibration",
        "summary": "WNBA needs calibration.",
        "reason": "User-selected sport WNBA needs paper calibration samples.",
        "props": [],
        "button_label": "Load Paper",
    }])
    monkeypatch.setattr(web_app, "_market_timing_alert_rows", lambda *args, **kwargs: [{
        "type": "Take Now",
        "action": "Good timing",
        "reason": "Positive EV with no major line move yet.",
        "player": "D",
        "stat": "PRA",
        "direction": "Over",
        "line": 31.5,
        "platform": "PrizePicks",
        "sport": "WNBA",
        "confidence": 62,
        "edge": 1.1,
        "priority_score": 80,
    }])

    body = daily_briefing("PrizePicks", "WNBA")

    assert body["headline"].startswith("1 playable")
    assert body["summary"]["confirmed_props"] == 12
    assert body["summary"]["analyzed_props"] == 15
    assert body["summary"]["slate"][0]["sport"] == "WNBA"
    assert body["top_opportunities"]
    assert body["user"]["display_name"] == "Joshua"
    assert body["user"]["greeting"].endswith("Joshua.")
    assert body["provider_badges"][0]["entry_capable"] is True
    assert "bet" in body["empty_states"]
    assert body["summary"]["risk_level"] == "Medium"
    assert body["suggested_entries"][0]["label"] == "2-Leg"
    assert body["games_today"][0]["game"] == "AAA-BBB"
    assert body["games_today"][0]["matchup_label"] == "AAA vs BBB"
    assert body["games_today"][0]["generated_entry"]["props"]
    assert body["sections"]["bet"][0]["button_label"] == "Load Slip"
    assert body["sections"]["bet"][0]["explanation"]["evidence"]
    assert body["sections"]["bet"][0]["explanation"]["freshness"]["label"]
    assert body["sections"]["bet"][0]["suggestion"] == command_card["suggestion"]
    assert body["sections"]["paper"][0].get("entry_mode") == "paper" or body["sections"]["paper"][0]["type"] == "paper"
    assert body["sections"]["watch"][0]["title"] == "Take Now"
    assert body["sections"]["avoid"]
    assert "require user confirmation" in body["rules"][0]


def test_daily_game_card_infers_matchup_from_team_and_opponent_code(monkeypatch):
    monkeypatch.setattr(web_app, "_player_availability_payload", lambda *args, **kwargs: {
        "availability_score": 90,
        "status": "Likely Active",
        "player": args[0] if args else "",
    })

    card = web_app._daily_game_card("PrizePicks", "WNBA", "GSV", [
        {"player": "A", "team": "IND", "sport": "WNBA", "stat": "Points", "direction": "Over", "line": 20.5, "confidence": 64, "edge": 1.2, "platform": "PrizePicks", "game": "GSV", "trending_count": 1000},
        {"player": "B", "team": "IND", "sport": "WNBA", "stat": "Assists", "direction": "Over", "line": 6.5, "confidence": 58, "edge": 0.8, "platform": "PrizePicks", "game": "GSV", "trending_count": 800},
    ])

    assert card["matchup_label"] == "IND vs GSV"
    assert card["teams"] == ["IND", "GSV"]


def test_entry_progress_light_mode_skips_provider_backfills(monkeypatch):
    pending = [{
        "id": 1,
        "platform": "PrizePicks",
        "average_confidence": 60,
        "average_edge": 1.0,
        "wager": 10,
        "multiplier": 3,
        "potential_payout": 30,
        "profit": 0,
        "status": "Pending",
        "result": "",
        "placed_at": utc_now(),
        "props": [{
            "player": "A",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "projection": 22,
            "edge": 1.5,
            "confidence": 60,
            "direction": "Over",
            "platform": "PrizePicks",
            "game": "AAA-BBB",
            "game_time": "",
        }],
    }]
    called = {"live": 0, "times": 0}
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: pending)
    monkeypatch.setattr(web_app, "_refresh_live_stats", lambda entries: called.__setitem__("live", called["live"] + 1))
    monkeypatch.setattr(web_app, "_backfill_missing_game_times", lambda entries: called.__setitem__("times", called["times"] + 1))
    monkeypatch.setattr(web_app, "_usable_final_stat_for_entry", lambda prop, entry: None)

    body = entry_progress(auto_check=False, refresh_providers=False, market_detail=False)

    assert body["active"] == 1
    assert body["live_stats_sync"]["skipped"] is True
    assert body["game_time_sync"]["skipped"] is True
    assert body["entries"][0]["legs"][0]["clv"]["clv"] is None
    assert "fast startup" in body["entries"][0]["legs"][0]["clv"]["note"]
    assert called == {"live": 0, "times": 0}


def test_daily_briefing_hides_real_money_card_when_threshold_misses(monkeypatch):
    card = {
        "type": "entry",
        "title": "Best 3-Leg",
        "summary": "Primary daily parlay candidate.",
        "score": 71.0,
        "grade": "C",
        "action": "Borderline",
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "direction": "Over", "line": 20.5, "confidence": 54, "edge": 0.3, "platform": "PrizePicks"},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "direction": "Over", "line": 6.5, "confidence": 53, "edge": 0.2, "platform": "PrizePicks"},
        ],
        "suggestion": {"entry": {"props": []}},
        "warnings": [],
        "trust": {"score": 53, "label": "Paper First"},
        "timing": {"score": 55, "label": "Monitor"},
        "stake": {"amount": 4.0, "unit_label": "Balanced sizing"},
        "explanation": {"legs": []},
    }

    cards = web_app._daily_bet_cards([card])

    assert cards == []


def test_daily_briefing_uses_cached_payload_until_refresh(monkeypatch):
    store = {}
    calls = {"count": 0}

    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))

    def fake_payload(platform, sport):
        calls["count"] += 1
        return {
            "as_of": f"run-{calls['count']}",
            "platform": platform,
            "sport": sport or "All Sports",
            "headline": "cached test",
            "summary": {},
            "sections": {"bet": [], "paper": [], "watch": [], "avoid": []},
            "rules": [],
        }

    monkeypatch.setattr(web_app, "_daily_briefing_payload", fake_payload)

    first = web_app._cached_daily_briefing_payload("PrizePicks", "WNBA")
    second = web_app._cached_daily_briefing_payload("PrizePicks", "WNBA")
    refreshed = web_app._cached_daily_briefing_payload("PrizePicks", "WNBA", refresh=True)

    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True
    assert second["as_of"] == first["as_of"]
    assert refreshed["cache"]["hit"] is False
    assert refreshed["as_of"] == "run-2"
    assert calls["count"] == 2


def test_daily_briefing_cache_expires(monkeypatch):
    expired = iso_utc(utc_now() - timedelta(hours=1))
    store = {
        "daily_briefing_cache:prizepicks:wnba": json.dumps({
            "created_at": iso_utc(utc_now() - timedelta(hours=12)),
            "expires_at": expired,
            "version": web_app.DAILY_BRIEFING_CACHE_VERSION,
            "payload": {"as_of": "old", "headline": "old cache"},
        })
    }
    calls = {"count": 0}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))

    def fake_payload(platform, sport):
        calls["count"] += 1
        return {
            "as_of": "new",
            "platform": platform,
            "sport": sport or "All Sports",
            "headline": "rebuilt",
            "summary": {},
            "sections": {"bet": [], "paper": [], "watch": [], "avoid": []},
            "rules": [],
        }

    monkeypatch.setattr(web_app, "_daily_briefing_payload", fake_payload)

    body = web_app._cached_daily_briefing_payload("PrizePicks", "WNBA")

    assert body["cache"]["hit"] is True
    assert body["cache"]["stale"] is True
    assert body["cache"]["requires_refresh"] is True
    assert body["as_of"] == "old"
    assert calls["count"] == 0

    refreshed = web_app._cached_daily_briefing_payload("PrizePicks", "WNBA", refresh=True)

    assert refreshed["cache"]["hit"] is False
    assert refreshed["cache"]["stale"] is False
    assert refreshed["as_of"] == "new"
    assert calls["count"] == 1


def test_daily_briefing_cached_only_returns_placeholder_without_provider_scan(monkeypatch):
    calls = {"payload": 0}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": default)
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "bankroll": 100.0,
        "profit": 0.0,
        "roi": 0.0,
        "monthly_profit": {"current_month": {"profit": 0.0, "roi": 0.0}},
    })
    monkeypatch.setattr(web_app, "_model_health_payload", lambda: {"trust_score": 0, "status": "Scan Needed"})

    def fail_payload(platform, sport):
        calls["payload"] += 1
        raise AssertionError("Provider scan should not run for cached-only initial load")

    monkeypatch.setattr(web_app, "_daily_briefing_payload", fail_payload)

    body = web_app._cached_daily_briefing_payload("PrizePicks", "WNBA", cached_only=True)

    assert body["cache"]["cached_only"] is True
    assert body["cache"]["requires_refresh"] is True
    assert body["summary"]["risk_level"] == "Scan Needed"
    assert calls["payload"] == 0


def test_daily_briefing_scan_writes_status_and_run_log(monkeypatch):
    store = {}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(web_app, "_daily_briefing_payload", lambda platform, sport: {
        "as_of": "scan-test",
        "platform": platform,
        "sport": sport or "All Sports",
        "headline": "scan ready",
        "summary": {
            "analyzed_props": 42,
            "confirmed_props": 30,
            "risk_level": "Medium",
            "expected_value": 7.5,
        },
        "games_today": [{"game": "AAA-BBB"}],
        "sections": {
            "bet": [{"title": "Bet"}],
            "paper": [],
            "watch": [{"title": "Watch"}],
            "avoid": [],
        },
        "rules": [],
    })

    scan = web_app._run_daily_briefing_scan("PrizePicks", "WNBA", scan_id="scan123", trigger="test")
    status = web_app._daily_scan_status_payload("PrizePicks", "WNBA")

    assert scan["status"] == "ready"
    assert scan["summary"]["analyzed_props"] == 42
    assert scan["summary"]["games"] == 1
    assert status["current"]["id"] == "scan123"
    assert status["runs"][0]["id"] == "scan123"


def test_daily_briefing_scan_failure_is_logged(monkeypatch):
    store = {}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(web_app, "_daily_briefing_payload", lambda platform, sport: (_ for _ in ()).throw(RuntimeError("provider down")))

    scan = web_app._run_daily_briefing_scan("PrizePicks", "WNBA", scan_id="scanfail", trigger="test")
    status = web_app._daily_scan_status_payload("PrizePicks", "WNBA")

    assert scan["status"] == "failed"
    assert "provider down" in scan["errors"][0]
    assert status["runs"][0]["status"] == "failed"


def test_entry_suggestions_limit_both_to_entry_platforms(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [{
        "player": f"{platform} Player",
        "team": "AAA",
        "league": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "platform": platform,
    }])

    def fake_suggest_entries(raw_props, sport, platform_model, **kwargs):
        calls.append(platform_model.value)
        return []

    monkeypatch.setattr(web_app, "suggest_entries", fake_suggest_entries)

    entry_suggestions(sport="WNBA", platform="Both", leg_count=3)

    assert calls == ["PrizePicks", "Underdog", "Sleeper"]


def test_context_only_platform_falls_back_for_entry_suggestions(monkeypatch):
    fetched = []
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: fetched.append(platform) or [{
        "player": "A",
        "team": "AAA",
        "league": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "platform": platform,
    }])
    monkeypatch.setattr(web_app, "suggest_entries", lambda *args, **kwargs: [])

    entry_suggestions(sport="WNBA", platform="Ball Don't Lie", leg_count=3)

    assert fetched == ["PrizePicks"]


def test_advantage_center_watchlist_boost_and_game_context(monkeypatch):
    props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA-BBB", "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 21.5, "game": "AAA-BBB", "trending_count": 90000, "platform": "Underdog"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 6.5, "game": "AAA-BBB", "trending_count": 80000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "game": "CCC-DDD", "trending_count": 70000, "platform": "PrizePicks"},
        {"player": "D", "team": "DDD", "league": "WNBA", "stat": "Points", "line": 14.5, "game": "CCC-DDD", "trending_count": 60000, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: props)
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "bankroll": 100.0,
        "record": "0-0",
        "profit": 0.0,
        "roi": 0.0,
        "recommendation_accuracy": {},
        "entries": {"paper": {"decisions": 0}},
        "by_sport": {},
        "by_platform": {},
        "by_stat": {},
    })
    monkeypatch.setattr(web_app, "_player_availability_payload", lambda player, sport, team="", game="": {
        "player": player,
        "sport": sport,
        "team": team,
        "game": game,
        "availability_score": 88.0,
        "status": "Likely Active",
        "factors": [],
    })

    body = web_app.advantage_center(platform="Both", sport="WNBA")
    watch_alerts = web_app._watchlist_alerts([{
        "id": "a",
        "player": "A",
        "sport": "WNBA",
        "stat": "Points",
        "platform": "Both",
        "direction": "Over",
        "target_line": 20.5,
        "alert_when": "at_or_better",
        "move_threshold": 1.0,
    }])
    boost = web_app.boost_analysis(web_app.BoostAnalysisPayload(
        player="A",
        sport="WNBA",
        stat="Points",
        direction="Over",
        original_line=21.5,
        boosted_line=20.5,
    ))
    context = web_app.game_context(game="AAA-BBB", sport="WNBA", platform="Both")

    assert len(body["competitive_features"]) == 10
    assert body["top_recommendation"]["trust"]["score"] >= 0
    assert watch_alerts[0]["player"] == "A"
    assert boost["boosted"]["ev"] >= boost["original"]["ev"]
    assert context["game"] == "AAA-BBB"
    assert context["ranked_players"]


def test_model_health_returns_actionable_components():
    body = model_health()

    assert "trust_score" in body
    assert "calibration" in body["components"]
    assert body["next_steps"]


def test_data_health_schedule_notifications_and_availability(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app, "_market_timing_alert_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app, "fetch_injuries", lambda sport: [{"player": "A", "team": "AAA", "status": "🟡 Questionable", "detail": "ankle", "sport": sport}])
    monkeypatch.setattr(web_app.newsapi, "fetch_context", lambda *args, **kwargs: [])

    health_body = web_app.data_health()
    sleeper_body = web_app.sleeper_status()
    schedule_body = web_app.refresh_schedule()
    notifications_body = web_app.notifications()
    availability_body = web_app.player_availability("A", sport="WNBA", team="AAA")

    assert health_body["summary"]["total"] >= 5
    assert "provider_weights" in health_body
    sleeper_health = next(provider for provider in health_body["providers"] if provider["name"] == "Sleeper")
    assert sleeper_health["status"] == "available"
    assert sleeper_health["auth_required"] is False
    assert sleeper_health["key_env"] == ""
    assert sleeper_body["auth_required"] is False
    assert sleeper_body["read_only"] is True
    assert schedule_body["jobs"]
    assert "notifications" in notifications_body
    assert availability_body["status"] == "Questionable"
    assert availability_body["availability_score"] < 86


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


def test_web_entry_analysis_uses_espn_history_for_auto_projection(monkeypatch):
    history = [
        {"actual": 30.0, "status": "played"},
        {"actual": 28.0, "status": "played"},
        {"actual": 26.0, "status": "played"},
        {"actual": 0.0, "status": "dnp"},
    ]
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda player, stat, sport=None, limit=100: history[:limit])

    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.0},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Points", "line": 18.0},
                ],
            }
        )
    )

    first = body["entry"]["props"][0]
    assert first["projection_source"] == "multi_source_fusion"
    assert first["projection"] > 20.0
    assert first["espn"]["sample_size"] == 3
    assert first["espn"]["hit_rate"] == 100.0
    assert body["espn_context"]["props_with_history"] == 2


def test_entry_analysis_combines_injury_line_and_consensus_signals(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app,
        "fetch_injuries",
        lambda sport: [{"player": "A", "team": "AAA", "status": "🟡 Questionable", "detail": "ankle", "sport": sport}],
    )
    monkeypatch.setattr(
        web_app.LineHistoryRepository,
        "get_history",
        lambda player, stat, platform: [{"line": 19.5, "recorded_at": datetime(2026, 7, 8, 12, 0)}],
    )
    monkeypatch.setattr(
        web_app,
        "_fetch_props",
        lambda platform, sport: [
            {"player": "A", "league": "WNBA", "stat": "Points", "line": 21.5, "platform": "PrizePicks"},
            {"player": "A", "league": "WNBA", "stat": "Points", "line": 22.0, "platform": "Underdog"},
        ],
    )

    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Rebounds", "line": 8.5},
                ],
            }
        )
    )

    signals = body["entry"]["props"][0]["source_signals"]
    sources = {signal["source"] for signal in signals}
    assert {"ESPN injuries", "Line movement", "Platform consensus"} <= sources
    assert body["source_fusion"]["signal_count"] >= 3


def test_entry_analysis_marks_nba_summer_league_context(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "fetch_injuries", lambda sport: [])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])
    monkeypatch.setattr(web_app.newsapi, "fetch_context", lambda *args, **kwargs: [])

    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {
                        "player": "Summer Player",
                        "team": "LAL",
                        "sport": "NBA",
                        "stat": "Points",
                        "line": 18.5,
                        "game": "NBA Summer League",
                        "season_type": "summer_league",
                        "trending_count": 100000,
                    },
                    {
                        "player": "Other Player",
                        "team": "BOS",
                        "sport": "NBA",
                        "stat": "Rebounds",
                        "line": 7.5,
                        "game": "NBA Summer League",
                        "season_type": "summer_league",
                        "trending_count": 90000,
                    },
                ],
            }
        )
    )

    first = body["entry"]["props"][0]
    sources = {signal["source"] for signal in first["source_signals"]}
    assert first["season_type"] == "summer_league"
    assert "NBA Summer League context" in sources
    assert "NBA Summer League" in first["data_quality"]["flags"][0]
    assert any(item["label"] == "Historical data" and item["status"] == "warning" for item in body["confirmation_checklist"])


def test_entry_analysis_includes_sleeper_trend_signal(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "fetch_injuries", lambda sport: [])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])
    monkeypatch.setattr(
        web_app.sleeper,
        "player_trend_signal",
        lambda player, sport: {"add_count": 80, "drop_count": 10, "net_adds": 70},
    )

    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "NFL", "stat": "Receiving Yards", "line": 52.5},
                    {"player": "B", "team": "BBB", "sport": "NFL", "stat": "Rushing Yards", "line": 62.5},
                ],
            }
        )
    )

    assert "Sleeper trends" in {signal["source"] for signal in body["entry"]["props"][0]["source_signals"]}


def test_entry_analysis_includes_news_weather_and_balldontlie_signals(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "fetch_injuries", lambda sport: [])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])
    monkeypatch.setattr(web_app.sleeper, "player_trend_signal", lambda player, sport: None)
    monkeypatch.setattr(
        web_app.balldontlie,
        "stat_signal",
        lambda player, stat, sport: {"average": 25.0, "sample_size": 5},
    )
    monkeypatch.setattr(
        web_app.newsapi,
        "fetch_context",
        lambda query, days=7, page_size=5: [{"title": "Player injury note", "description": "questionable"}],
    )
    monkeypatch.setattr(web_app.newsapi, "risk_terms", lambda articles: ["injury"])
    monkeypatch.setattr(
        web_app.openweather,
        "fetch_weather_for_game",
        lambda game, sport: {"wind_mph": 18, "condition": "Clear"},
    )
    monkeypatch.setattr(
        web_app.openweather,
        "weather_signal",
        lambda weather: {"impact": -3.0, "message": "Wind 18 mph may suppress outdoor production."},
    )

    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "NFL", "stat": "Receiving Yards", "line": 52.5, "game": "BUF@NE"},
                    {"player": "B", "team": "BBB", "sport": "NFL", "stat": "Rushing Yards", "line": 62.5},
                ],
            }
        )
    )

    sources = {signal["source"] for signal in body["entry"]["props"][0]["source_signals"]}
    assert {"Ball Don't Lie stats", "NewsAPI", "OpenWeather"} <= sources


def test_sleeper_trend_signal_combines_adds_and_drops(monkeypatch):
    monkeypatch.setattr(
        sleeper,
        "fetch_trending_players",
        lambda sport, trend_type: [
            {"player": "Player A", "count": 40 if trend_type == "add" else 5}
        ],
    )

    signal = sleeper.player_trend_signal("Player A", "NFL")

    assert signal["add_count"] == 40
    assert signal["drop_count"] == 5
    assert signal["net_adds"] == 35


def test_expanded_stat_mapping_preserves_major_sport_props():
    assert _stat_from_text("PRA") == StatType.PRA
    assert _stat_from_text("Points + Rebounds + Assists") == StatType.PRA
    assert _stat_from_text("Pts+Rebs+Asts") == StatType.PRA
    assert _stat_from_text("Pitcher Strikeouts") == StatType.PITCHER_STRIKEOUTS
    assert _stat_from_text("Receiving Yards") == StatType.RECEIVING_YARDS
    assert _stat_from_text("Shots on Goal") == StatType.SHOTS_ON_GOAL
    assert _stat_from_text("Significant Strikes") == StatType.SIGNIFICANT_STRIKES


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


def test_fetch_props_supports_configured_platform(monkeypatch):
    monkeypatch.setattr(
        web_app.sleeper,
        "fetch_projections",
        lambda: [
            {
                "player": "Sleeper Player",
                "team": "SP",
                "league": "WNBA",
                "stat": "Points",
                "line": 18.5,
                "trending_count": 10,
            }
        ],
    )

    props = web_app._fetch_props("Sleeper", "WNBA")

    assert props[0]["platform"] == "Sleeper"
    assert props[0]["player"] == "Sleeper Player"


def test_generic_prop_normalizer_accepts_csv_payload():
    payload = "player,sport,stat,line,team,game,rank\nA,WNBA,Points,20.5,AAA,BBB,7"

    props = normalize_props(payload, "Custom Feed")

    assert props == [
        {
            "projection_id": "custom feed-0",
            "player": "A",
            "team": "AAA",
            "league": "WNBA",
            "position": "",
            "stat": "Points",
            "line": 20.5,
            "direction": "",
            "game": "BBB",
            "game_time": "",
            "season_type": "regular",
            "status": "pre_game",
            "trending_count": 999993,
            "rank": 7,
            "image_url": "",
            "platform": "Custom Feed",
        }
    ]


def test_generic_prop_normalizer_marks_nba_summer_league():
    payload = "player,sport,stat,line,team,game,rank\nA,NBASL,Points,20.5,AAA,NBA Summer League,7"

    props = normalize_props(payload, "Custom Feed")

    assert props[0]["league"] == "NBA"
    assert props[0]["season_type"] == "summer_league"


def test_uploaded_csv_props_are_extracted_and_analyzed(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    payload = "player,sport,stat,line,team,platform\nA,WNBA,Points,20.5,AAA,PrizePicks\nB,WNBA,Rebounds,8.5,BBB,PrizePicks"

    body = analyze_uploaded_file(
        UploadAnalyzePayload(
            file_name="props.csv",
            mime_type="text/csv",
            target="entry",
            source="PrizePicks",
            content_base64=base64.b64encode(payload.encode("utf-8")).decode("utf-8"),
        )
    )

    assert body["kind"] == "props"
    assert body["prop_count"] == 2
    assert body["analysis"]["entry"]["props"][0]["player"] == "A"


def test_uploaded_screenshot_without_openai_key_returns_guidance(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    body = analyze_uploaded_file(
        UploadAnalyzePayload(
            file_name="slip.png",
            mime_type="image/png",
            target="entry",
            content_base64=base64.b64encode(b"fake-image").decode("utf-8"),
        )
    )

    assert body["kind"] == "image"
    assert body["ai_enabled"] is False
    assert body["props"] == []


def test_uploaded_phone_screenshot_can_import_bet_history(monkeypatch):
    saved = []
    monkeypatch.setattr(
        web_app,
        "_openai_extract_bets_from_image",
        lambda raw, mime_type: {
            "platform": "PrizePicks",
            "bets": [
                {
                    "sport": "WNBA",
                    "game": "DAL-TOR",
                    "description": "A Points",
                    "odds": -110,
                    "wager": 10,
                    "result": "Win",
                    "profit": None,
                    "stat_type": "Points",
                    "win_probability": 58,
                }
            ],
        },
    )
    monkeypatch.setattr(web_app.BetRepository, "save", lambda self, bet: saved.append(bet))

    body = analyze_uploaded_file(
        UploadAnalyzePayload(
            file_name="phone-history.png",
            mime_type="image/png",
            target="bet_history",
            source="PrizePicks",
            content_base64=base64.b64encode(b"fake-image").decode("utf-8"),
        )
    )

    assert body["kind"] == "bet_history"
    assert body["ai_enabled"] is True
    assert body["imported"] == 1
    assert saved[0].platform == "PrizePicks"
    assert saved[0].profit == 9.09


def test_calibration_feedback_can_boost_confidence_from_history(monkeypatch):
    bets = [
        Bet("WNBA", "DAL-TOR", "A Points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 50),
        Bet("WNBA", "DAL-TOR", "B Points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 50),
        Bet("WNBA", "DAL-TOR", "C Points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 50),
    ]
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: bets)
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])

    signals = _calibration_feedback_signals(
        PropPayload(player="A", team="DAL", sport="WNBA", stat="Points", line=20.5, platform="PrizePicks")
    )

    assert signals
    assert signals[0]["source"] == "Calibration feedback"
    assert signals[0]["confidence_delta"] > 0


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


def test_fetch_props_filters_season_long_underdog_markets(monkeypatch):
    monkeypatch.setattr(
        web_app.underdog,
        "fetch_projections",
        lambda: [
            {
                "player": "Jared Goff",
                "team": "DET",
                "league": "NFL",
                "stat": "Season Pass Yards",
                "line": 4074.5,
                "platform": "Underdog",
                "season_type": "season_long",
            },
            {
                "player": "",
                "team": "DET",
                "league": "NFL",
                "stat": "Pass Yards",
                "line": 271.5,
                "platform": "Underdog",
                "game_time": "2026-09-13T17:00:00Z",
            },
            {
                "player": "Paige Bueckers",
                "team": "DAL",
                "league": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "platform": "Underdog",
                "game_time": "2026-07-14T19:00:00-04:00",
            },
        ],
    )

    props = web_app._fetch_props("Underdog", None)

    assert [prop["player"] for prop in props] == ["Paige Bueckers"]


def test_placement_check_flags_missing_time_and_changed_line(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_fetch_platform_props",
        lambda platform: [
            {
                "player": "Paige Bueckers",
                "team": "DAL",
                "league": "WNBA",
                "stat": "Points",
                "line": 21.5,
                "platform": platform,
                "game_time": "",
            }
        ],
    )

    body = placement_check(
        EntryPayload.model_validate(
            {
                "platform": "Underdog",
                "wager": 10,
                "multiplier": 3,
                "props": [
                    {
                        "player": "Paige Bueckers",
                        "team": "DAL",
                        "sport": "WNBA",
                        "stat": "Points",
                        "line": 20.5,
                        "platform": "Underdog",
                    }
                ],
            }
        )
    )

    assert body["ok"] is True
    assert body["requires_confirmation"] is True
    assert any("game time is unavailable" in warning for warning in body["warnings"])
    assert any("current Underdog line is 21.5" in warning for warning in body["warnings"])


def test_ai_parlay_chat_falls_back_to_best_candidate(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)

    body = ai_parlay_chat(ParlayChatPayload(message="you need a parlay?", platform="PrizePicks", sport="WNBA"))

    assert body["ai_enabled"] is False
    assert body["suggestion"]["leg_count"] == 3
    assert "best 3-leg parlay" in body["message"]


def test_ai_parlay_chat_uses_message_sport_and_leg_count_without_openai(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "WNBA", "stat": "3-Pointers Made", "line": 2.5, "trending_count": 70000},
        {"player": "NFL A", "team": "EEE", "league": "NFL", "stat": "Receiving Yards", "line": 45.5, "trending_count": 999999},
        {"player": "NFL B", "team": "FFF", "league": "NFL", "stat": "Rushing Yards", "line": 52.5, "trending_count": 999998},
        {"player": "NFL C", "team": "GGG", "league": "NFL", "stat": "Passing Yards", "line": 230.5, "trending_count": 999997},
        {"player": "NFL D", "team": "HHH", "league": "NFL", "stat": "Receptions", "line": 4.5, "trending_count": 999996},
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)

    body = ai_parlay_chat(
        ParlayChatPayload(
            message="give me a 4 leg parlay for WNBA",
            platform="PrizePicks",
            sport="All Sports",
        )
    )

    assert body["ai_enabled"] is False
    assert body["request"]["sport"] == "WNBA"
    assert body["request"]["leg_count"] == 4
    assert body["suggestion"]["leg_count"] == 4
    assert {prop["sport"] for prop in body["suggestion"]["entry"]["props"]} == {"WNBA"}
    assert "best 4-leg parlay for WNBA" in body["message"]


def test_ai_parlay_chat_parses_risk_and_confirmation_intent():
    request = _parse_parlay_request("Give me a safer confirmed 2-leg parlay for hockey", "All Sports")

    assert request["sport"] == "NHL"
    assert request["leg_count"] == 2
    assert request["risk_profile"] == "safe"
    assert request["confirmed_only"] is True


def test_ai_parlay_chat_falls_back_when_openai_request_errors(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "NHL", "stat": "Shots on Goal", "line": 2.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "NHL", "stat": "Saves", "line": 28.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "NHL", "stat": "Goals", "line": 0.5, "trending_count": 80000},
    ]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)
    monkeypatch.setattr(web_app, "_openai_parlay_response", lambda message, suggestions, request=None: (None, "timeout"))

    body = ai_parlay_chat(ParlayChatPayload(message="give me a 3 leg parlay for hockey", platform="PrizePicks", sport="All Sports"))

    assert body["ai_enabled"] is False
    assert body["ai_error"] == "timeout"
    assert body["request"]["sport"] == "NHL"
    assert body["suggestion"]["leg_count"] == 3
    assert "best 3-leg parlay for NHL" in body["message"]


def test_ai_parlay_chat_returns_structured_context(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "WNBA", "stat": "3-Pointers Made", "line": 2.5, "trending_count": 70000},
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)

    body = ai_parlay_chat(ParlayChatPayload(message="safer 3 leg WNBA", platform="PrizePicks", sport="All Sports"))

    assert body["request"]["risk_profile"] == "safe"
    assert body["search"]["exclude_correlated"] is True
    assert body["local_model"]["reasons"]
    assert "alternatives" in body


def test_ai_status_reports_key_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-an-openai-key")

    body = ai_status()

    assert body["configured"] is True
    assert body["key_format_ok"] is False


def test_ai_entry_review_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])

    body = ai_entry_review(
        AiEntryReviewPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Rebounds", "line": 8.5},
                ],
            }
        )
    )

    assert body["ai_enabled"] is False
    assert body["model"] == "edgeiq-local-v1.0"
    assert "Rules review" in body["review"]


def test_place_entry_saves_wager_and_multiplier(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        lambda entry, status="Draft", result="", wager=0.0, multiplier=1.0, recommended_by_app=False, audit_snapshot="", entry_mode="real": saved.setdefault(
            "payload",
            {"status": status, "wager": wager, "multiplier": multiplier, "recommended_by_app": recommended_by_app, "audit_snapshot": audit_snapshot, "entry_mode": entry_mode},
        ) or 11,
    )
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 90.0})
    monkeypatch.setattr(web_app, "_placement_check", lambda payload: {
        "ok": True,
        "requires_confirmation": False,
        "warnings": [],
        "blocks": [],
        "props": [],
        "provider_rows": 0,
    })

    body = place_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "wager": 10,
                "multiplier": 3,
                "recommended_by_app": True,
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
                ],
            }
        )
    )

    assert body["status"] == "Pending"
    assert saved["payload"]["status"] == "Pending"
    assert saved["payload"]["wager"] == 10.0
    assert saved["payload"]["multiplier"] == 3.0
    assert saved["payload"]["recommended_by_app"] is True
    assert "recommendation" in saved["payload"]["audit_snapshot"]


def test_place_entry_enriches_missing_game_context_from_provider(monkeypatch):
    saved = {}
    provider_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@BBB", "game_time": "2026-07-16T23:00:00Z", "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "game": "AAA@BBB", "game_time": "2026-07-16T23:00:00Z", "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: provider_props)
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 90.0})

    def fake_save(entry, **kwargs):
        saved["props"] = entry.props
        return 13

    monkeypatch.setattr(web_app.EntryRepository, "save", fake_save)

    place_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "wager": 10,
                "multiplier": 3,
                "props": [
                    {"player": "A", "team": "", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "", "sport": "WNBA", "stat": "Assists", "line": 7.5},
                ],
            }
        )
    )

    assert saved["props"][0].game == "AAA@BBB"
    assert saved["props"][0].game_time == "2026-07-16T23:00:00Z"
    assert saved["props"][0].player.team == "AAA"


def test_place_paper_entry_does_not_require_wager(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        lambda entry, status="Draft", result="", wager=0.0, multiplier=1.0, recommended_by_app=False, audit_snapshot="", entry_mode="real": saved.setdefault(
            "payload",
            {"status": status, "wager": wager, "multiplier": multiplier, "entry_mode": entry_mode, "audit_snapshot": audit_snapshot},
        ) or 12,
    )
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 90.0})

    body = place_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "entry_mode": "paper",
                "wager": 0,
                "multiplier": 3,
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
                ],
            }
        )
    )

    assert body["entry_mode"] == "paper"
    assert saved["payload"]["entry_mode"] == "paper"
    assert saved["payload"]["wager"] == 0
    assert '"entry_mode": "paper"' in saved["payload"]["audit_snapshot"]


def test_auto_paper_calibration_creates_zero_wager_paper_entries(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000, "platform": "PrizePicks"},
    ]
    saved = {}
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"entries": {"paper": {"pending": 1}}})
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)

    def fake_save(entry, status="Draft", result="", wager=0.0, multiplier=1.0, recommended_by_app=False, audit_snapshot="", entry_mode="real"):
        saved["payload"] = {
            "status": status,
            "wager": wager,
            "multiplier": multiplier,
            "recommended_by_app": recommended_by_app,
            "audit_snapshot": audit_snapshot,
            "entry_mode": entry_mode,
            "props": entry.props,
        }
        return 81

    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        fake_save,
    )

    body = auto_paper_calibration(
        AutoPaperCalibrationPayload(
            sport="WNBA",
            leg_count=2,
            max_entries=1,
            prefer_confirmed=False,
        )
    )

    assert body["created_count"] == 1
    assert body["created"][0]["id"] == 81
    assert saved["payload"]["status"] == "Pending"
    assert saved["payload"]["entry_mode"] == "paper"
    assert saved["payload"]["wager"] == 0.0
    assert saved["payload"]["recommended_by_app"] is True
    assert "auto_paper_calibration" in saved["payload"]["audit_snapshot"]


def test_auto_paper_calibration_dry_run_does_not_save(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.EntryRepository, "save", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry run should not save")))

    body = auto_paper_calibration(
        AutoPaperCalibrationPayload(
            sport="WNBA",
            leg_count=2,
            max_entries=1,
            prefer_confirmed=False,
            dry_run=True,
        )
    )

    assert body["dry_run"] is True
    assert body["created_count"] == 1
    assert body["created"][0]["id"] is None
    assert body["dashboard"] is None


def test_auto_paper_calibration_all_sports_confirmed_finds_dominant_sport(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props if sport in (None, "WNBA") else [])
    monkeypatch.setattr(
        web_app,
        "_confirmed_props_payload",
        lambda platform, sport, limit=120: {"raw_props": raw_props if sport == "WNBA" else [], "count": len(raw_props), "sport": sport or "WNBA"},
    )

    body = auto_paper_calibration(
        AutoPaperCalibrationPayload(
            sport="All Sports",
            leg_count=2,
            max_entries=1,
            prefer_confirmed=True,
            dry_run=True,
        )
    )

    assert body["created_count"] == 1
    assert {prop["sport"] for prop in body["created"][0]["suggestion"]["entry"]["props"]} == {"WNBA"}


def test_entry_analysis_serializes_under_direction(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 18.0},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "projection": 8.0},
                ],
            }
        )
    )

    assert body["entry"]["props"][0]["direction"] == "Under"
    assert body["entry"]["props"][1]["direction"] == "Over"


def test_under_leg_result_wins_below_line():
    assert _leg_result(17.0, 20.5, "Under") == "Win"
    assert _leg_result(24.0, 20.5, "Under") == "Loss"
    assert _leg_result(20.5, 20.5, "Under") == "Push"


def test_recommendation_accuracy_counts_only_recommended_decisions():
    entries = [
        {"status": "Settled", "result": "Win", "recommended_by_app": True},
        {"status": "Settled", "result": "Loss", "recommended_by_app": True},
        {"status": "Settled", "result": "Push", "recommended_by_app": True},
        {"status": "Pending", "result": "", "recommended_by_app": True},
        {"status": "Settled", "result": "Win", "recommended_by_app": False},
    ]

    stats = EntryRepository._recommendation_accuracy(entries)

    assert stats["accuracy"] == 50.0
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["pushes"] == 1
    assert stats["pending"] == 1
    assert stats["tracked"] == 4


def test_entry_profit_uses_multiplier_as_net_profit():
    assert EntryRepository._profit_for_result("Win", 10, 3) == 20
    assert EntryRepository._profit_for_result("Loss", 10, 3) == -10
    assert EntryRepository._profit_for_result("Push", 10, 3) == 0


def test_dnp_reduce_mode_uses_remaining_leg_multiplier():
    result, profit = EntryRepository._settlement_profit(
        result="Win",
        wager=10,
        multiplier=5,
        leg_count=3,
        dnp_legs=1,
        dnp_mode="reduce",
    )

    assert result == "Win"
    assert profit == 20


def test_dnp_refund_mode_pushes_entry():
    result, profit = EntryRepository._settlement_profit(
        result="Win",
        wager=10,
        multiplier=5,
        leg_count=3,
        dnp_legs=1,
        dnp_mode="refund",
    )

    assert result == "Push"
    assert profit == 0


def test_default_multiplier_is_inferred_from_leg_count():
    assert EntryRepository._default_multiplier_for_legs(2) == 3.0
    assert EntryRepository._default_multiplier_for_legs(3) == 5.0
    assert EntryRepository._default_multiplier_for_legs(99) == 3.0


def test_entry_platform_profitability_is_ranked_by_profit():
    groups = {
        "PrizePicks": {"entries": 2, "wins": 1, "losses": 1, "pushes": 0, "profit": 5.0, "wagered": 20.0, "roi": 25.0, "win_pct": 50.0},
        "Underdog": {"entries": 1, "wins": 1, "losses": 0, "pushes": 0, "profit": 40.0, "wagered": 10.0, "roi": 400.0, "win_pct": 100.0},
    }

    ranked = EntryRepository._ranked_groups(groups)

    assert ranked[0]["platform"] == "Underdog"
    assert ranked[0]["rank"] == 1


def test_paper_entries_excluded_from_financial_totals(monkeypatch):
    entries = [
        {
            "status": "Settled",
            "result": "Win",
            "entry_mode": "real",
            "wager": 10.0,
            "profit": 20.0,
            "recommended_by_app": True,
            "average_confidence": 62.0,
            "props": [{"sport": "WNBA"}],
            "platform": "PrizePicks",
            "grade": "B",
        },
        {
            "status": "Settled",
            "result": "Loss",
            "entry_mode": "paper",
            "wager": 0.0,
            "profit": 0.0,
            "recommended_by_app": True,
            "average_confidence": 58.0,
            "props": [{"sport": "WNBA"}],
            "platform": "PrizePicks",
            "grade": "C",
        },
        {
            "status": "Pending",
            "result": "",
            "entry_mode": "paper",
            "wager": 0.0,
            "profit": 0.0,
            "recommended_by_app": True,
            "average_confidence": 55.0,
            "props": [{"sport": "NFL"}],
            "platform": "Underdog",
            "grade": "B",
        },
    ]
    monkeypatch.setattr(EntryRepository, "all", lambda: entries)

    stats = EntryRepository.financial_stats()

    assert stats["wagered"] == 10.0
    assert stats["profit"] == 20.0
    assert stats["pending_exposure"] == 0.0
    assert stats["paper"]["active"] == 2
    assert stats["paper"]["decisions"] == 1
    assert stats["paper"]["accuracy"] == 0.0


def test_entry_suggestions_include_four_and_five_leg_high_risk(monkeypatch):
    raw_props = [
        {
            "player": f"P{i}",
            "team": f"T{i}",
            "league": "WNBA",
            "stat": "Points",
            "line": 10.5 + i,
            "trending_count": 100000 - i,
            "platform": "PrizePicks",
        }
        for i in range(8)
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)

    body = entry_suggestions(sport="WNBA", platform="PrizePicks")

    assert body["mode"] == "balanced_with_higher_risk"
    assert len(body["suggestions"]) == 5
    assert [suggestion["rank"] for suggestion in body["suggestions"]] == [1, 2, 3, 4, 5]
    assert [suggestion["leg_count"] for suggestion in body["suggestions"]] == [2, 2, 3, 4, 5]
    assert all(suggestion["risk_tier"] == "Higher Risk" for suggestion in body["suggestions"][-2:])


def test_confirmed_props_require_game_time_and_clean_market(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game_time": "2026-07-14T19:00:00-04:00", "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Points", "line": 18.5, "game_time": "", "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "NFL", "stat": "Season Pass Yards", "line": 4000.5, "game_time": "2026-09-01T13:00:00-04:00", "trending_count": 80000, "platform": "Underdog", "season_type": "season_long"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [prop for prop in raw_props if sport is None or prop["league"] == sport])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = confirmed_props(platform="PrizePicks", sport="WNBA", limit=10)

    assert body["count"] == 1
    assert body["props"][0]["player"] == "A"
    assert body["props"][0]["confirmation"]["game_time_confirmed"] is True


def test_confirmed_entry_suggestions_use_confirmed_pool(monkeypatch):
    raw_props = [
        {
            "player": f"P{i}",
            "team": f"T{i}",
            "league": "WNBA",
            "stat": "Points",
            "line": 10.5 + i,
            "game_time": "2026-07-14T19:00:00-04:00",
            "trending_count": 100000 - i,
            "platform": "PrizePicks",
        }
        for i in range(8)
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = confirmed_entry_suggestions(sport="WNBA", platform="PrizePicks")

    assert body["mode"] == "confirmed_props_top_5"
    assert body["confirmed_count"] == 8
    assert [suggestion["leg_count"] for suggestion in body["suggestions"]] == [2, 2, 3, 4, 5]


def test_bankroll_transaction_endpoint_returns_dashboard(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web_app.BankrollTransactionRepository,
        "save",
        lambda transaction_type, amount, note="": saved.setdefault(
            "transaction",
            {"transaction_type": transaction_type, "amount": amount, "note": note},
        ),
    )
    monkeypatch.setattr(
        web_app.BankrollTransactionRepository,
        "summary",
        lambda: {"deposits": 100.0, "withdrawals": 25.0, "net": 75.0, "count": 2, "transactions": []},
    )
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 175.0})

    body = save_bankroll_transaction(
        BankrollTransactionPayload(transaction_type="Withdrawal", amount=25.0, note="Cash out")
    )

    assert saved["transaction"] == {"transaction_type": "Withdrawal", "amount": 25.0, "note": "Cash out"}
    assert body["summary"]["net"] == 75.0
    assert body["dashboard"]["bankroll"] == 175.0


def test_classify_default_wagers_endpoint_returns_dashboard(monkeypatch):
    monkeypatch.setattr(
        web_app.EntryRepository,
        "classify_missing_economics",
        lambda: {"updated": 2, "pending": 1, "settled": 1, "default_wager": 10.0},
    )
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 90.0})

    body = classify_default_entry_wagers()

    assert body["updated"] == 2
    assert body["pending"] == 1
    assert body["settled"] == 1
    assert body["dashboard"] == {"bankroll": 90.0}


def test_dnp_setting_endpoints(monkeypatch):
    saved = {}
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: saved.update({key: value}))
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": "refund")

    assert dnp_setting() == {"mode": "refund"}
    assert update_dnp_setting(DnpSettingPayload(mode="ignore")) == {"mode": "ignore"}
    assert saved == {"dnp_handling": "ignore"}


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


def test_line_shop_finds_best_lines_and_no_vig_price(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 1000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 21.5, "trending_count": 900, "platform": "Underdog"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Points", "line": 10.5, "trending_count": 800, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = line_shop("A", "Points", sport="WNBA", platform="Both", over_odds=-115, under_odds=-105)

    assert body["available"] is True
    assert body["best_over"]["platform"] == "PrizePicks"
    assert body["best_over"]["line"] == 20.5
    assert body["best_under"]["platform"] == "Underdog"
    assert body["consensus_line"] == 21.0
    assert body["no_vig"]["hold"] > 0


def test_player_research_combines_active_props_and_final_history(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 1000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 21.5, "trending_count": 900, "platform": "Underdog"},
    ]
    history = [
        {"player": "A", "sport": "WNBA", "stat": "Points", "game": "AAA-BBB", "game_date": "2026-07-01", "actual": 25, "status": "played", "source": "test"},
        {"player": "A", "sport": "WNBA", "stat": "Points", "game": "AAA-CCC", "game_date": "2026-07-02", "actual": 18, "status": "played", "source": "test"},
        {"player": "A", "sport": "WNBA", "stat": "Points", "game": "AAA-DDD", "game_date": "2026-07-03", "actual": 24, "status": "played", "source": "test"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: history)

    body = player_research("A", "Points", sport="WNBA", platform="Both", line=20.5)

    assert body["history_count"] == 3
    assert body["splits"]["last_5"]["hit_rate"] == 66.7
    assert body["active_props"][0]["platform"] == "PrizePicks"
    assert body["recommendation"]["player"] == "A"


def test_sharp_consensus_returns_fair_line_and_market_width(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 1000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 21.5, "trending_count": 900, "platform": "Underdog"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = sharp_consensus("A", "Points", sport="WNBA", platform="Both", over_odds=-110, under_odds=-110)

    assert body["available"] is True
    assert body["fair_line"] == 21.0
    assert body["market_width"] == 1.0
    assert body["confidence"] == "Strong"


def test_hedge_calculator_balances_two_outcomes():
    body = hedge_calculator(HedgeCalculatorPayload(original_odds=-110, hedge_odds=-110, original_stake=11))

    profits = [row["profit"] for row in body["outcomes"]]
    assert body["hedge_stake"] > 0
    assert profits[0] == profits[1]


def test_middle_calculator_identifies_middle_zone():
    body = middle_calculator(MiddleCalculatorPayload(over_line=20.5, under_line=22.5, over_stake=11, under_stake=11))

    assert body["middle_available"] is True
    assert body["middle_zone"]["width"] == 2.0
    assert body["outcomes"][1]["profit"] > 0


def test_alert_delivery_settings_round_trip(monkeypatch):
    store = {}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))

    body = update_alert_delivery_settings(AlertDeliveryPayload(email_enabled=True, email_address="josh@example.com"))

    assert body["settings"]["channels"] == ["browser", "email"]
    assert body["delivery_hooks"]["email"] == "configured"


def test_import_wizard_exposes_provider_templates(monkeypatch):
    monkeypatch.setattr(web_app, "_sportsbook_integrations_payload", lambda: {"providers": []})

    body = import_wizard()

    assert body["templates"][0]["platform"] == "PrizePicks"
    assert body["templates"][1]["platform"] == "Underdog"


def test_platform_value_check_recommends_best_app_for_entry(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "PRA", "line": 20.5, "trending_count": 1000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points + Rebounds + Assists", "line": 19.5, "trending_count": 900, "platform": "Underdog"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 800, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.0, "trending_count": 700, "platform": "Underdog"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [
        prop for prop in raw_props
        if platform == "Both" or prop["platform"] == platform
    ])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = web_app.platform_value_check(
        EntryPayload.model_validate({
            "platform": "PrizePicks",
            "props": [
                {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "PRA", "line": 20.5, "direction": "Over"},
                {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "direction": "Over"},
            ],
        })
    )

    assert body["recommended_platform"] == "Underdog"
    assert body["value_delta"] == 1.5
    assert "Underdog offers +1.50" in body["recommendation"]
    assert body["legs"][0]["best_line"] == 19.5


def test_sportsbook_integrations_reports_manual_handoff(monkeypatch):
    monkeypatch.delenv("EDGEIQ_BET_HISTORY_FILE", raising=False)
    monkeypatch.delenv("EDGEIQ_FINAL_STATS_FILE", raising=False)

    body = web_app.sportsbook_integrations()

    assert body["connected"] is False
    assert body["import_ready"] is False
    assert any(connector["name"] == "PrizePicks" for connector in body["connectors"])
    assert "credentials" in body["privacy_note"]


def test_opportunity_feed_blends_ev_timing_and_watchlist(monkeypatch):
    monkeypatch.setattr(web_app, "_ev_scanner_rows", lambda *args, **kwargs: [{
        "player": "A",
        "sport": "WNBA",
        "platform": "PrizePicks",
        "direction": "Over",
        "stat": "Points",
        "line": 20.5,
        "projection": 23,
        "confidence": 61,
        "edge": 2.5,
        "expected_value": 8.2,
        "data_quality": {"score": 74},
        "data_strength": [],
        "auto_projected": False,
        "provider_backed": True,
        "probability_adjustment": "No material probability adjustment.",
    }])
    monkeypatch.setattr(web_app, "_market_timing_alert_rows", lambda *args, **kwargs: [{
        "type": "Take Now",
        "action": "Good timing",
        "priority_score": 70,
        "player": "B",
        "sport": "WNBA",
        "platform": "Underdog",
        "direction": "Under",
        "stat": "Assists",
        "line": 7.5,
        "projection": 6.8,
        "confidence": 59,
        "edge": 0.7,
        "expected_value": 3.1,
        "reason": "Positive EV with no major line move yet.",
        "data_quality": {"score": 70},
        "data_strength": [],
    }])
    monkeypatch.setattr(web_app, "_watchlist_alerts", lambda: [{
        "player": "C",
        "platform": "PrizePicks",
        "direction": "Over",
        "stat": "Rebounds",
        "line": 8.5,
        "reason": "Over line is at or below target 8.5.",
        "prop": {"sport": "WNBA", "confidence": 57, "edge": 1.0},
    }])

    body = web_app.opportunity_feed(platform="Both", sport="WNBA", min_ev=0, limit=5)

    assert body["count"] == 3
    assert {row["type"] for row in body["opportunities"]} == {"Positive EV", "Take Now", "Watchlist"}
    assert body["opportunities"][0]["priority_score"] >= body["opportunities"][-1]["priority_score"]


def test_entry_handoff_returns_copy_ready_slip(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 1000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 19.5, "trending_count": 900, "platform": "Underdog"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 800, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.0, "trending_count": 700, "platform": "Underdog"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [
        prop for prop in raw_props
        if platform == "Both" or prop["platform"] == platform
    ])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = web_app.entry_handoff(
        EntryPayload.model_validate({
            "platform": "PrizePicks",
            "entry_mode": "paper",
            "multiplier": 3,
            "props": [
                {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "direction": "Over"},
                {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "direction": "Over"},
            ],
        })
    )

    assert body["recommended_platform"] == "Underdog"
    assert "EdgeIQ 2-leg handoff" in body["copy_text"]
    assert body["legs"][0]["best_platform"] == "Underdog"
    assert body["checklist"]


def test_ev_scanner_ranks_positive_ev_props(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 1, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = ev_scanner(platform="PrizePicks", sport="WNBA", min_ev=0, limit=5, odds=-110)

    assert body["count"] >= 1
    assert body["props"][0]["expected_value"] > 0
    assert body["props"][0]["estimated_probability"] > body["props"][0]["sportsbook_probability"]


def test_prizepicks_adjusted_lines_use_standard_baseline(monkeypatch):
    raw_props = [
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100, "platform": "PrizePicks", "odds_type": "standard"},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 18.5, "trending_count": 90, "platform": "PrizePicks", "odds_type": "goblin", "adjusted_odds": True},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 24.5, "trending_count": 80, "platform": "PrizePicks", "odds_type": "demon", "adjusted_odds": True},
    ]
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    enriched = web_app._enrich_prizepicks_adjusted_lines(raw_props)
    discounted = next(prop for prop in enriched if prop["line_offer_type"] == "goblin")
    analyzed = web_app._analyzed_feed_prop(discounted)

    assert discounted["standard_line"] == 20.5
    assert analyzed["baseline_line"] == 20.5
    assert analyzed["line"] == 18.5
    assert analyzed["is_discounted_line"] is True
    assert analyzed["edge"] > 2
    assert any(label["label"] == "Discounted line" for label in analyzed["data_strength"])


def test_ev_scanner_prefers_discounted_prizepicks_line_over_max_line(monkeypatch):
    raw_props = [
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100, "platform": "PrizePicks", "odds_type": "standard"},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 18.5, "trending_count": 90, "platform": "PrizePicks", "odds_type": "goblin", "adjusted_odds": True},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 24.5, "trending_count": 80, "platform": "PrizePicks", "odds_type": "demon", "adjusted_odds": True},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: web_app._enrich_prizepicks_adjusted_lines(raw_props))
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = ev_scanner(platform="PrizePicks", sport="WNBA", min_ev=-100, limit=5, odds=-110)

    assert body["props"][0]["player"] == "A"
    assert body["props"][0]["line"] == 18.5
    assert body["props"][0]["standard_line"] == 20.5
    assert body["props"][0]["is_discounted_line"] is True
    assert body["props"][0]["line"] != 24.5


def test_market_timing_alerts_detect_steam_move(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 22.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 90000, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(
        web_app.LineHistoryRepository,
        "get_history",
        lambda player, stat, platform: [{"line": 20.5, "recorded_at": datetime(2026, 7, 10, 10, 0)}] if player == "A" else [],
    )

    body = market_timing_alerts(platform="PrizePicks", sport="WNBA", limit=5)

    assert body["count"] >= 1
    assert body["alerts"][0]["type"] == "Steam Move"
    assert body["alerts"][0]["market_supports_pick"] is True


def test_clv_report_compares_placed_line_to_current_line(monkeypatch):
    monkeypatch.setattr(
        web_app.EntryRepository,
        "all",
        lambda: [
            {
                "id": 1,
                "status": "Pending",
                "result": "",
                "platform": "PrizePicks",
                "placed_at": datetime(2026, 7, 8, 12, 0),
                "props": [
                    {"player": "A", "sport": "WNBA", "stat": "Points", "line": 20.5, "platform": "PrizePicks"}
                ],
            }
        ],
    )
    monkeypatch.setattr(web_app, "_active_line_for_player_stat", lambda *args, **kwargs: 22.5)

    body = clv_report()

    assert body["tracked_legs"] == 1
    assert body["average_clv"] == 2.0
    assert body["entries"][0]["legs"][0]["beat_market"] is True


def test_sync_run_classifies_imports_and_auto_checks(monkeypatch, tmp_path):
    stats_file = tmp_path / "stats.csv"
    bets_file = tmp_path / "bets.csv"
    stats_file.write_text("player,sport,stat,game,game_date,actual\nA,WNBA,Points,SEA,2026-07-08,24\n")
    bets_file.write_text("sport,game,description,odds,wager,result\nWNBA,SEA,A points,-110,10,Win\n")
    monkeypatch.setenv("EDGEIQ_FINAL_STATS_FILE", str(stats_file))
    monkeypatch.setenv("EDGEIQ_BET_HISTORY_FILE", str(bets_file))
    monkeypatch.setattr(web_app.EntryRepository, "classify_missing_economics", lambda: {"updated": 1})
    monkeypatch.setattr(web_app, "import_final_stats", lambda payload, source: 1)
    monkeypatch.setattr(web_app, "_import_betting_history_payload", lambda payload, source: {"imported": 1, "skipped": 0})
    monkeypatch.setattr(web_app, "auto_check_entries", lambda allow_estimates=False: {"checked": 2, "settled": 1})
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"record": "1-0"})

    body = run_sync()

    assert body["default_wagers"]["updated"] == 1
    assert body["final_stats_file"]["imported"] == 1
    assert body["bet_history_file"]["imported"] == 1
    assert body["auto_check"]["settled"] == 1


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


def test_projection_assist_returns_model_recommendation():
    body = projection_assist(
        ProjectionAssistPayload(
            player="A",
            sport="WNBA",
            stat="Points",
            line=20.5,
            projection=23.0,
            trending_count=10000,
        )
    )

    assert body["projection"] == 23.0
    assert body["edge"] > 0
    assert body["grade"] in {"A", "B", "C", "D"}


def test_parse_betting_history_csv():
    rows = _parse_betting_history("sport,game,description,odds,wager,result\nWNBA,A-B,A points,-110,10,Win")

    assert rows[0]["sport"] == "WNBA"
    assert rows[0]["result"] == "Win"


def test_import_betting_history_saves_valid_rows(monkeypatch):
    saved = []
    monkeypatch.setattr(web_app.BetRepository, "save", lambda self, bet: saved.append(bet))
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 100})

    body = import_betting_history(
        BettingHistoryPayload(
            payload="sport,game,description,odds,wager,result\nWNBA,A-B,A points,-110,10,Win",
            source="history",
        )
    )

    assert body["imported"] == 1
    assert body["skipped"] == 0
    assert saved[0].profit == 9.09


def test_entry_to_bet_history_row_includes_source_metadata():
    bet = BetRepository._entry_to_bet({
        "id": 77,
        "platform": "PrizePicks",
        "wager": 10.0,
        "profit": 20.0,
        "result": "Win",
        "average_confidence": 61.5,
        "entry_mode": "paper",
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "line": 20.5, "direction": "Over", "game": "NYL @ MIN"},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "line": 5.5, "direction": "Under", "game": "NYL @ MIN"},
        ],
    })

    assert bet.source == "edgeiq_entry"
    assert bet.source_entry_id == 77
    assert bet.entry_mode == "paper"
    assert bet.sport == "WNBA"
    assert bet.game == "NYL @ MIN"
    assert bet.stat_type == "Assists"
    assert "A Over Points 20.5" in bet.description


def test_bets_endpoint_includes_completed_entry_leg_final_stats(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "sync_settled_to_bet_history", lambda: {"synced": 0})
    monkeypatch.setattr(
        web_app.EntryRepository,
        "all",
        lambda: [
            {
                "id": 77,
                "platform": "PrizePicks",
                "entry_mode": "real",
                "status": "Settled",
                "result": "Win",
                "wager": 10.0,
                "multiplier": 3.0,
                "profit": 20.0,
                "placed_at": datetime(2026, 7, 10, 4, 10),
                "settled_at": datetime(2026, 7, 10, 23, 0),
                "average_confidence": 61.5,
                "average_edge": 1.2,
                "props": [
                    {
                        "player": "A",
                        "team": "NYL",
                        "sport": "WNBA",
                        "stat": "Points",
                        "direction": "Over",
                        "line": 20.5,
                        "projection": 23.0,
                        "actual": 24.0,
                        "final_result": "Win",
                        "final_source": "espn",
                        "final_status": "played",
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self, include_synced_entries=False: [])

    body = bets()

    assert body["entries"][0]["calibration_legs"] == 1
    assert body["entries"][0]["props"][0]["actual"] == 24.0
    assert body["entries"][0]["props"][0]["source"] == "espn"
    assert body["entries"][0]["props"][0]["result"] == "Win"


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
    assert "paid_ready_count" in body
    assert "best_value_pick" in body
    assert "obstacles" in body
    assert all("platform_value" in suggestion for suggestion in body["suggestions"])
    assert all("value_adjusted_score" in suggestion for suggestion in body["suggestions"])


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
    assert isinstance(body["obstacles"], list)


def test_auto_check_result_can_settle_with_projection_estimates(monkeypatch):
    settled = {}
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
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


def test_auto_check_stores_leg_result_snapshots(monkeypatch):
    settled = {}

    def fake_settle(entry_id, result, **kwargs):
        settled["entry_id"] = entry_id
        settled["result"] = result
        settled["leg_results"] = kwargs["leg_results"]

    monkeypatch.setattr(web_app.EntryRepository, "settle", fake_settle)
    entry = {
        "id": 43,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 24.0},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=True)

    assert body["settled"] is True
    assert settled["entry_id"] == 43
    assert settled["leg_results"][0]["actual"] == 24.0
    assert settled["leg_results"][0]["source"] == "projection_estimate"
    assert settled["leg_results"][0]["final_status"] == "estimated"


def test_auto_check_result_can_settle_with_final_stats_file(monkeypatch, tmp_path):
    stats_file = tmp_path / "final_stats.json"
    stats_file.write_text(
        '{"stats":[{"player":"A","sport":"WNBA","stat":"Points","game":"SEA","actual":24}]}',
        encoding="utf-8",
    )
    final_stats._load_stats.cache_clear()
    monkeypatch.setenv("EDGEIQ_FINAL_STATS_FILE", str(stats_file))
    settled = {}
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
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


def test_auto_check_result_uses_pra_alias_for_final_stats_file(monkeypatch, tmp_path):
    stats_file = tmp_path / "final_stats.json"
    stats_file.write_text(
        '{"stats":[{"player":"A","sport":"WNBA","stat":"PRA","game":"SEA","actual":31}]}',
        encoding="utf-8",
    )
    final_stats._load_stats.cache_clear()
    monkeypatch.setenv("EDGEIQ_FINAL_STATS_FILE", str(stats_file))
    monkeypatch.setattr(web_app.FinalStatsRepository, "find_result", lambda prop: None)
    settled = {}
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
    entry = {
        "id": 8,
        "props": [
            {
                "player": "A",
                "team": "AAA",
                "sport": "WNBA",
                "stat": "Points + Rebounds + Assists",
                "line": 28.5,
                "projection": 25.0,
                "game": "SEA",
            },
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is True
    assert body["result"] == "Win"
    assert body["legs"][0]["actual"] == 31
    assert settled == {8: "Win"}


def test_backfill_entry_final_stats_stores_snapshots(monkeypatch):
    stored = {}
    monkeypatch.setattr(
        web_app.EntryRepository,
        "all",
        lambda: [
            {
                "id": 9,
                "status": "Settled",
                "result": "Win",
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 24.0},
                ],
            }
        ],
    )
    monkeypatch.setattr(web_app, "_final_stat_for_prop", lambda prop: None)
    monkeypatch.setattr(
        web_app.EntryRepository,
        "store_settled_leg_results",
        lambda entry_id, legs: stored.update({"entry_id": entry_id, "legs": legs}),
    )

    body = backfill_entry_final_stats()

    assert body["backfilled"] == 1
    assert body["leg_rows"] == 1
    assert body["estimated_leg_rows"] == 1
    assert stored["entry_id"] == 9
    assert stored["legs"][0]["source"] == "projection_estimate"
    final_stats._load_stats.cache_clear()


def test_entry_progress_payload_reports_leg_status_from_final_stats(monkeypatch):
    monkeypatch.setattr(web_app, "_final_stat_for_prop", lambda prop: {"actual": 24.0, "status": "played", "source": "test"})
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
    assert body["live_result"] == "Win"
    assert body["placed_at"] == "2026-07-08T12:00:00+00:00"
    assert body["legs"][0]["status"] == "Win"
    assert body["legs"][0]["progress_percent"] == 100.0
    assert body["legs"][0]["stat_bubble"] == "24 / 20.5"


def test_entry_progress_ignores_stale_final_stats_before_placed_date(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_final_stat_for_prop",
        lambda prop: {"actual": 12.0, "status": "played", "source": "test", "game_date": "2026-07-08"},
    )
    entry = {
        "id": 91,
        "platform": "PrizePicks",
        "placed_at": datetime(2026, 7, 9, 12, 0),
        "average_confidence": 62.0,
        "average_edge": -1.5,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 18.0, "game": "SEA"},
        ],
    }

    body = _entry_progress_payload(entry)

    assert body["completed_legs"] == 0
    assert body["live_result"] == "In Progress"
    assert body["projected_result"] == "Loss"
    assert body["source"] == "unavailable"
    assert body["legs"][0]["status"] == "Pending"
    assert body["legs"][0]["final_status"] == "pending"
    assert body["legs"][0]["progress_percent"] == 0.0
    assert body["legs"][0]["projection_progress_percent"] == 87.8
    assert body["legs"][0]["progress_label"] == "Waiting for live stat data / 20.5"
    assert body["legs"][0]["timeline_status"] == "time_unknown"
    assert body["legs"][0]["stat_bubble"] == "TBD"


def test_entry_progress_live_stat_moves_meter_without_completing_leg(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_final_stat_for_prop",
        lambda prop: {"actual": 12.0, "status": "live", "source": "test", "game_date": "2026-07-09"},
    )
    entry = {
        "id": 92,
        "platform": "PrizePicks",
        "placed_at": datetime(2026, 7, 9, 12, 0),
        "average_confidence": 62.0,
        "average_edge": 1.5,
        "props": [
            {
                "player": "A",
                "team": "AAA",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "projection": 24.0,
                "game": "SEA",
                "game_time": "2026-07-09T23:30:00Z",
            },
        ],
    }

    body = _entry_progress_payload(entry)

    assert body["completed_legs"] == 0
    assert body["live_result"] == "In Progress"
    assert body["projected_result"] == "Win"
    assert body["source"] == "live_provider"
    assert body["legs"][0]["status"] == "Pending"
    assert body["legs"][0]["final_status"] == "live"
    assert body["legs"][0]["progress_percent"] == 58.5
    assert body["legs"][0]["progress_label"] == "Live 12 / 20.5"
    assert body["legs"][0]["stat_bubble"] == "12 / 20.5"
    assert body["legs"][0]["game_time_label"] == "2026-07-09T23:30:00+00:00"
    assert body["next_game_time_label"] == "2026-07-09T23:30:00+00:00"


def test_entry_progress_groups_legs_by_start_time():
    entry = {
        "id": 88,
        "platform": "PrizePicks",
        "placed_at": datetime(2026, 7, 12, 18, 55),
        "average_confidence": 62.0,
        "average_edge": 1.5,
        "props": [
            {
                "player": "Late Leg",
                "team": "IND",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "projection": 24.0,
                "game": "LVA",
                "game_time": "2026-07-13T01:00:00Z",
            },
            {
                "player": "Paige Bueckers",
                "team": "DAL",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "projection": 24.0,
                "game": "CHI",
                "game_time": "2026-07-12T23:00:00Z",
            },
        ],
    }

    body = _entry_progress_payload(entry)

    assert [group["game_time_label"] for group in body["time_groups"]] == [
        "2026-07-12T23:00:00+00:00",
        "2026-07-13T01:00:00+00:00",
    ]
    assert body["time_groups"][0]["legs"][0]["player"] == "Paige Bueckers"
    assert body["time_groups"][1]["legs"][0]["player"] == "Late Leg"


def test_entry_progress_marks_scheduled_and_awaiting_live_legs(monkeypatch):
    monkeypatch.setattr(web_app, "utc_now", lambda: datetime(2026, 7, 12, 22, 0))
    monkeypatch.setattr(web_app, "_final_stat_for_prop", lambda prop: None)
    entry = {
        "id": 89,
        "platform": "PrizePicks",
        "placed_at": datetime(2026, 7, 12, 18, 55),
        "average_confidence": 62.0,
        "average_edge": 1.5,
        "props": [
            {
                "player": "Started Leg",
                "team": "WAS",
                "sport": "WNBA",
                "stat": "Points",
                "line": 23.5,
                "projection": 24.5,
                "game": "SEA",
                "game_time": "2026-07-12T19:00:00Z",
            },
            {
                "player": "Paige Bueckers",
                "team": "DAL",
                "sport": "WNBA",
                "stat": "Points",
                "line": 21.5,
                "projection": 22.3,
                "game": "CHI",
                "game_time": "2026-07-12T23:00:00Z",
            },
        ],
    }

    body = _entry_progress_payload(entry)

    assert body["tracker_status"] == "In Progress"
    assert body["legs"][0]["timeline_status"] == "awaiting_live"
    assert body["legs"][0]["progress_text"] == "Awaiting live stats · Projection 24.5"
    assert body["legs"][0]["stat_bubble"] == "Waiting"
    assert body["legs"][1]["timeline_status"] == "scheduled"
    assert body["legs"][1]["progress_text"] == "Scheduled · Projection 22.3"
    assert body["legs"][1]["stat_bubble"] == "Scheduled"


def test_auto_check_does_not_settle_from_stale_final_stats(monkeypatch):
    settled = {}
    monkeypatch.setattr(
        web_app,
        "_final_stat_for_prop",
        lambda prop: {"actual": 12.0, "status": "played", "source": "test", "game_date": "2026-07-08"},
    )
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
    entry = {
        "id": 92,
        "placed_at": datetime(2026, 7, 9, 12, 0),
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 24.0, "game": "SEA"},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is False
    assert body["result"] == "Unknown"
    assert body["source"] == "unavailable"
    assert settled == {}


def test_auto_check_result_reduces_dnp_legs(monkeypatch):
    settled = {}
    final_stats_by_player = {
        "A": {"actual": 24.0, "status": "played", "source": "test"},
        "B": {"actual": 0.0, "status": "dnp", "source": "test"},
    }
    monkeypatch.setattr(web_app, "_final_stat_for_prop", lambda prop: final_stats_by_player[prop["player"]])
    monkeypatch.setattr(
        web_app.EntryRepository,
        "settle",
        lambda entry_id, result, **kwargs: settled.update({entry_id: {"result": result, **kwargs}}),
    )
    entry = {
        "id": 10,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 19.0},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "projection": 8.0},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is True
    assert body["result"] == "Win"
    assert body["legs"][1]["result"] == "DNP"
    assert settled[10]["dnp_legs"] == 1


def test_auto_check_settles_loss_when_one_leg_loses_and_others_are_unknown(monkeypatch):
    settled = {}
    final_stats_by_player = {
        "A": {"actual": 17.0, "status": "played", "source": "test"},
        "B": None,
    }
    monkeypatch.setattr(web_app, "_final_stat_for_prop", lambda prop: final_stats_by_player[prop["player"]])
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
    entry = {
        "id": 42,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 22.0},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Points", "line": 15.5, "projection": 16.0},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is True
    assert body["result"] == "Loss"
    assert settled == {42: "Loss"}


def test_espn_basketball_summary_parser_creates_played_and_dnp_rows():
    summary = {
        "header": {
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "away", "team": {"abbreviation": "MIN"}},
                        {"homeAway": "home", "team": {"abbreviation": "CON"}},
                    ]
                }
            ]
        },
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "MIN"},
                    "statistics": [
                        {
                            "names": ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK"],
                            "athletes": [
                                {
                                    "didNotPlay": False,
                                    "athlete": {"displayName": "Courtney Williams"},
                                    "stats": ["30", "21", "8-14", "1-2", "4-5", "7", "5", "2", "1", "0"],
                                },
                                {
                                    "didNotPlay": True,
                                    "athlete": {"displayName": "No Play"},
                                    "stats": [],
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    }

    rows = espn._parse_basketball_summary(summary, "WNBA", datetime(2026, 7, 8).date())

    points = next(row for row in rows if row["player"] == "Courtney Williams" and row["stat"] == "Points")
    pra = next(row for row in rows if row["player"] == "Courtney Williams" and row["stat"] == "PRA")
    dnp = next(row for row in rows if row["player"] == "No Play" and row["stat"] == "Points")
    assert points["actual"] == 21
    assert pra["actual"] == 33
    assert points["game"] == "MIN@CON"
    assert dnp["status"] == "dnp"

    live_rows = espn._parse_basketball_summary(summary, "WNBA", datetime(2026, 7, 8).date(), row_status="live")
    live_points = next(row for row in live_rows if row["player"] == "Courtney Williams" and row["stat"] == "Points")
    assert live_points["status"] == "live"


def test_entry_progress_endpoint_uses_pending_entries(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])

    body = entry_progress()

    assert body == {
        "entries": [],
        "active": 0,
        "with_live_stats": 0,
        "auto_check": None,
        "game_time_sync": {"provider": "espn", "skipped": True, "updated": 0, "fetched_rows": 0, "errors": []},
        "live_stats_sync": {"provider": "espn_live", "skipped": True, "imported": 0, "fetched_rows": 0, "errors": []},
    }


def test_entry_progress_backfills_missing_game_times(monkeypatch):
    pending_without_time = {
        "id": 1,
        "platform": "PrizePicks",
        "average_confidence": 62.0,
        "average_edge": 2.5,
        "wager": 10.0,
        "multiplier": 5.0,
        "potential_payout": 50.0,
        "profit": 0.0,
        "placed_at": datetime(2026, 7, 9, 12, 0),
        "props": [
            {
                "player": "Paige Bueckers",
                "team": "DAL",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "projection": 23.0,
                "edge": 2.5,
                "confidence": 62.0,
                "direction": "Over",
                "platform": "PrizePicks",
                "game": "NY@DAL",
                "game_time": "",
            }
        ],
    }
    pending_with_time = {
        **pending_without_time,
        "props": [{**pending_without_time["props"][0], "game_time": "2026-07-09T23:30:00Z"}],
    }
    calls = {"pending": 0}

    def fake_pending():
        calls["pending"] += 1
        return [pending_without_time] if calls["pending"] == 1 else [pending_with_time]

    monkeypatch.setattr(web_app.EntryRepository, "pending", fake_pending)
    monkeypatch.setattr(
        web_app,
        "refresh_game_times_for_entries",
        lambda entries, lookback_days=2: {
            "provider": "espn",
            "fetched_rows": 1,
            "rows": [{"sport": "WNBA", "game": "NY@DAL", "game_time": "2026-07-09T23:30:00Z"}],
            "errors": [],
        },
    )
    monkeypatch.setattr(web_app.EntryRepository, "backfill_game_times", lambda rows, **kwargs: {"updated": 1})

    body = entry_progress()

    assert body["game_time_sync"]["updated"] == 1
    assert body["entries"][0]["next_game_time_label"] == "2026-07-09T23:30:00+00:00"


def test_game_time_backfill_requires_team_and_opponent_match():
    indexed = EntryRepository._index_game_times([
        {"sport": "WNBA", "game": "CHI@LA", "game_time": "2026-07-11T02:00Z"},
        {"sport": "WNBA", "game": "CHI@DAL", "game_time": "2026-07-12T23:00Z"},
    ])
    prop = SimpleNamespace(
        sport="WNBA",
        team="DAL",
        game="CHI",
    )

    matched = EntryRepository._matching_game_time(
        prop,
        indexed,
        datetime(2026, 7, 12, 18, 55),
    )

    assert matched == "2026-07-12T23:00Z"


def test_entry_progress_endpoint_can_run_local_auto_check(monkeypatch):
    calls = {}

    def fake_auto_check(allow_estimates=False, refresh_providers=True):
        calls["allow_estimates"] = allow_estimates
        calls["refresh_providers"] = refresh_providers
        return {"checked": 1, "settled": 1, "entries": [], "estimated": False, "final_stats_refresh": {}}

    monkeypatch.setattr(web_app, "_auto_check_pending_entries", fake_auto_check)
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])

    body = entry_progress(auto_check=True)

    assert calls == {"allow_estimates": False, "refresh_providers": True}
    assert body["auto_check"]["settled"] == 1


def test_entry_progress_refreshes_live_stats_by_default(monkeypatch):
    pending = [{
        "id": 1,
        "platform": "PrizePicks",
        "average_confidence": 60.0,
        "average_edge": 1.5,
        "wager": 10.0,
        "multiplier": 3.0,
        "potential_payout": 30.0,
        "profit": 0.0,
        "placed_at": datetime(2026, 7, 12, 18, 0),
        "props": [{
            "player": "Paige Bueckers",
            "team": "DAL",
            "sport": "WNBA",
            "stat": "Points",
            "line": 21.5,
            "projection": 22.3,
            "game": "CHI@DAL",
            "game_time": "2026-07-12T23:00:00+00:00",
        }],
    }]
    calls = {"live": 0}

    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: pending)
    monkeypatch.setattr(web_app, "_backfill_missing_game_times", lambda entries: {"provider": "espn", "updated": 0, "fetched_rows": 0, "errors": []})
    monkeypatch.setattr(
        web_app,
        "_refresh_live_stats",
        lambda entries: calls.update({"live": calls["live"] + 1}) or {"provider": "espn_live", "skipped": False, "imported": 1, "fetched_rows": 12, "errors": []},
    )
    monkeypatch.setattr(
        web_app,
        "_usable_final_stat_for_entry",
        lambda prop, entry: {"actual": 8.0, "status": "live", "source": "espn", "game_date": "2026-07-12"},
    )

    body = entry_progress()

    assert calls["live"] == 1
    assert body["with_live_stats"] == 1
    assert body["live_stats_sync"]["fetched_rows"] == 12
    assert body["entries"][0]["legs"][0]["progress_text"] == "Live 8 / 21.5"


def test_final_stats_match_provider_game_aliases():
    rows = [
        SimpleNamespace(game="NY@MIN", game_date="2026-07-11", id=1),
        SimpleNamespace(game="DAL@TOR", game_date="2026-07-10", id=2),
    ]

    assert _best_matching_row(rows, "NYL @ MIN").game == "NY@MIN"
    assert _best_matching_row(rows, "DAL @ TOR").game == "DAL@TOR"


def test_final_stats_ambiguous_rows_without_game_do_not_guess():
    rows = [
        SimpleNamespace(game="SEA@LV", game_date="2026-07-11", id=1),
        SimpleNamespace(game="SEA@PHX", game_date="2026-07-14", id=2),
    ]

    assert _best_matching_row(rows, "") is None


def test_final_stats_missing_game_can_match_exact_game_time_date():
    rows = [
        SimpleNamespace(game="SEA@LV", game_date="2026-07-11", id=1),
        SimpleNamespace(game="SEA@PHX", game_date="2026-07-14", id=2),
    ]

    assert _best_matching_row(rows, "", target_date="2026-07-14").game == "SEA@PHX"


def test_final_stats_match_short_opponent_with_team_context():
    rows = [
        SimpleNamespace(game="DAL@TOR", game_date="2026-07-10", id=1),
        SimpleNamespace(game="CHI@DAL", game_date="2026-07-12", id=2),
    ]

    assert _best_matching_row(rows, "CHI", "DAL").game == "CHI@DAL"


def test_final_stats_match_washington_provider_alias_with_team_context():
    rows = [
        SimpleNamespace(game="SEA@WSH", game_date="2026-07-12", id=1),
    ]

    assert _best_matching_row(rows, "SEA", "WAS").game == "SEA@WSH"


def test_dashboard_merges_entry_sport_performance_and_insights(monkeypatch):
    monkeypatch.setattr(dashboard_service, "get_starting_bankroll", lambda: 100.0)
    monkeypatch.setattr(
        dashboard_service.BetRepository,
        "dashboard_stats",
        lambda self: {
            "wins": 1,
            "losses": 0,
            "pushes": 0,
            "record": "1-0",
            "profit": 9.0,
            "wagered": 10.0,
            "roi": 90.0,
            "average": 9.0,
            "largest_win": 9.0,
            "largest_loss": 0.0,
            "current_streak": 1,
            "best_streak": 1,
            "worst_streak": 0,
            "max_drawdown": 0.0,
            "by_sport": {"WNBA": {"bets": 1, "wins": 1, "losses": 0, "pushes": 0, "profit": 9.0, "wagered": 10.0, "roi": 90.0, "win_pct": 100.0}},
            "by_stat": {},
            "by_platform": {},
            "bankroll_curve": [9.0],
        },
    )
    monkeypatch.setattr(
        dashboard_service.EntryRepository,
        "financial_stats",
        lambda: {
            "wins": 0,
            "losses": 1,
            "pushes": 0,
            "profit": -10.0,
            "wagered": 10.0,
            "pending_exposure": 0.0,
            "roi": -100.0,
            "recommendation_accuracy": {},
            "by_sport": {"WNBA": {"entries": 1, "wins": 0, "losses": 1, "pushes": 0, "profit": -10.0, "wagered": 10.0, "roi": -100.0, "win_pct": 0.0}},
            "by_stat": {},
            "by_platform": {"PrizePicks": {"entries": 1, "wins": 0, "losses": 1, "pushes": 0, "profit": -10.0, "wagered": 10.0, "roi": -100.0, "win_pct": 0.0}},
            "platform_profitability": [],
        },
    )
    monkeypatch.setattr(dashboard_service.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(dashboard_service.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(
        dashboard_service.BankrollTransactionRepository,
        "summary",
        lambda: {"deposits": 0.0, "withdrawals": 0.0, "net": 0.0, "count": 0, "transactions": []},
    )

    body = dashboard_service.get_dashboard()

    assert body["by_sport"]["WNBA"]["bets"] == 1
    assert body["by_sport"]["WNBA"]["entries"] == 1
    assert body["by_sport"]["WNBA"]["tracked"] == 2
    assert body["by_sport"]["WNBA"]["wins"] == 1
    assert body["by_sport"]["WNBA"]["losses"] == 1
    assert body["by_sport"]["WNBA"]["profit"] == -1.0
    assert body["performance_insights"]


def test_monthly_profit_log_groups_manual_bets_and_entries(monkeypatch):
    manual_bets = [
        Bet("WNBA", "A-B", "A points", -110, 10, "Win", 9.09, "PrizePicks", "Points", 65, created_at=datetime(2026, 7, 4, 12, 0)),
        Bet("NFL", "C-D", "C yards", -110, 20, "Loss", -20.0, "Underdog", "Receiving Yards", 55, created_at=datetime(2026, 8, 2, 12, 0)),
    ]
    entries = [
        {
            "status": "Settled",
            "result": "Win",
            "entry_mode": "real",
            "wager": 10.0,
            "profit": 20.0,
            "settled_at": datetime(2026, 7, 12, 20, 0),
        },
        {
            "status": "Settled",
            "result": "Win",
            "entry_mode": "paper",
            "wager": 0.0,
            "profit": 0.0,
            "settled_at": datetime(2026, 7, 12, 20, 0),
        },
    ]
    monkeypatch.setattr(dashboard_service.BetRepository, "get_all", lambda self: manual_bets)
    monkeypatch.setattr(dashboard_service.EntryRepository, "all", lambda: entries)

    monthly = dashboard_service.monthly_profit_log()
    by_month = {row["month"]: row for row in monthly["months"]}

    assert by_month["2026-07"]["profit"] == 29.09
    assert by_month["2026-07"]["wins"] == 2
    assert by_month["2026-07"]["tracked"] == 2
    assert by_month["2026-08"]["profit"] == -20.0
    assert monthly["months"][0]["month"] == "2026-08"


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
            "props": [
                {
                    "sport": "WNBA",
                    "stat": "Points",
                    "platform": "PrizePicks",
                    "confidence": 72.0,
                    "final_result": "Win",
                    "final_source": "sportsdataio",
                }
            ],
        },
        {
            "id": 2,
            "status": "Settled",
            "result": "Loss",
            "grade": "C",
            "average_confidence": 55.0,
            "wager": 10.0,
            "profit": -10.0,
            "props": [
                {
                    "sport": "WNBA",
                    "stat": "Assists",
                    "platform": "PrizePicks",
                    "confidence": 58.0,
                    "final_result": "Loss",
                    "final_source": "espn",
                }
            ],
        },
    ]
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: bets)
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)

    body = backtest()

    assert body["bets"]["count"] == 2
    assert body["entries"]["count"] == 2
    assert body["tracked"]["count"] == 4
    assert body["tracked"]["wins"] == 2
    assert body["tracked"]["losses"] == 2
    assert body["tracked"]["profit"] == 9.09
    assert body["entries"]["profit"] == 10.0
    assert body["entries"]["by_result"]["Win"]["profit"] == 20.0
    assert body["entries"]["by_result"]["Loss"]["profit"] == -10.0
    assert body["entries"]["by_grade"]["B"]["win_rate"] == 100.0
    assert body["calibration"]
    assert body["calibration_sources"]["prop_rows"] == 2
    assert body["calibration_sources"]["provider_rows"] == 2
    assert body["calibration_sources"]["sources"]["sportsdataio"] == 1


def test_refresh_calibration_data_imports_provider_rows_and_backfills(monkeypatch):
    calls = {"stored": 0}
    entries = [
        {
            "id": 7,
            "status": "Settled",
            "result": "Win",
            "average_confidence": 61.0,
            "wager": 0.0,
            "profit": 0.0,
            "props": [
                {
                    "player": "A",
                    "team": "AAA",
                    "sport": "NBA",
                    "stat": "Points",
                    "line": 20.5,
                    "confidence": 61.0,
                    "direction": "Over",
                }
            ],
        }
    ]

    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app, "_refresh_final_stats", lambda rows: {"provider": "espn+sportsdataio", "imported": 3, "fetched_rows": 3, "errors": []})
    monkeypatch.setattr(
        web_app,
        "_usable_final_stat_for_entry",
        lambda prop, entry: {"actual": 24.0, "status": "played", "source": "sportsdataio", "game_date": "2026-07-12"},
    )
    monkeypatch.setattr(
        web_app.EntryRepository,
        "store_settled_leg_results",
        lambda entry_id, legs: calls.update({"stored": calls["stored"] + 1, "entry_id": entry_id, "legs": legs}),
    )

    body = refresh_calibration_data()

    assert body["provider_refresh"]["imported"] == 3
    assert body["backfill"]["backfilled"] == 1
    assert body["backfill"]["provider_rows"] == 1
    assert calls["entry_id"] == 7
    assert calls["legs"][0]["source"] == "sportsdataio"
    assert body["backtest"]["calibration_sources"]["entry_rows"] == 1


def test_recheck_entry_final_stats_refreshes_backfills_and_settles_unknowns(monkeypatch):
    snapshots = [
        [
            {
                "id": 7,
                "status": "Settled",
                "result": "Win",
                "props": [
                    {"player": "A", "sport": "NBA", "stat": "PRA", "line": 31.5, "direction": "Over"},
                    {"player": "B", "sport": "NBA", "stat": "Points", "line": 20.5, "direction": "Over", "final_result": "Win"},
                ],
            },
            {
                "id": 8,
                "status": "Pending",
                "props": [
                    {"player": "C", "sport": "WNBA", "stat": "Rebounds", "line": 8.5, "direction": "Under"},
                ],
            },
        ],
        [
            {
                "id": 7,
                "status": "Settled",
                "result": "Win",
                "props": [
                    {"player": "A", "sport": "NBA", "stat": "PRA", "line": 31.5, "direction": "Over", "actual": 35, "final_result": "Win", "final_status": "played"},
                    {"player": "B", "sport": "NBA", "stat": "Points", "line": 20.5, "direction": "Over", "final_result": "Win"},
                ],
            },
            {
                "id": 8,
                "status": "Settled",
                "result": "Win",
                "props": [
                    {"player": "C", "sport": "WNBA", "stat": "Rebounds", "line": 8.5, "direction": "Under", "actual": 6, "final_result": "Win"},
                ],
            },
        ],
    ]
    calls = {"all": 0, "auto_allow_estimates": None, "auto_refresh": None}

    def fake_all():
        index = min(calls["all"], len(snapshots) - 1)
        calls["all"] += 1
        return snapshots[index]

    def fake_auto_check(allow_estimates=False, refresh_providers=True):
        calls["auto_allow_estimates"] = allow_estimates
        calls["auto_refresh"] = refresh_providers
        return {"checked": 1, "settled": 1, "entries": [], "estimated": False, "final_stats_refresh": {"skipped": True}}

    monkeypatch.setattr(web_app.EntryRepository, "all", fake_all)
    monkeypatch.setattr(web_app, "_refresh_final_stats", lambda rows: {"provider": "espn+sportsdataio", "imported": 2, "fetched_rows": 2, "errors": []})
    monkeypatch.setattr(web_app, "_backfill_settled_entry_leg_results", lambda rows: {"entries": 1, "backfilled": 1, "leg_rows": 2, "provider_rows": 1})
    monkeypatch.setattr(web_app, "_auto_check_pending_entries", fake_auto_check)

    body = recheck_entry_final_stats()

    assert body["unknown_before"] == 2
    assert body["unknown_after"] == 0
    assert body["cleared_unknowns"] == 2
    assert body["provider_refresh"]["imported"] == 2
    assert body["backfill"]["provider_rows"] == 1
    assert body["auto_check"]["settled"] == 1
    assert calls["auto_allow_estimates"] is False
    assert calls["auto_refresh"] is False


def test_recheck_entry_final_stats_corrects_completed_entry_result(monkeypatch):
    entries = [
        {
            "id": 21,
            "status": "Settled",
            "result": "Loss",
            "wager": 10,
            "multiplier": 3,
            "props": [
                {"player": "A", "sport": "WNBA", "stat": "Points", "line": 20.5, "direction": "Over"},
                {"player": "B", "sport": "WNBA", "stat": "Assists", "line": 7.5, "direction": "Under"},
            ],
        }
    ]
    settled = {}
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)
    monkeypatch.setattr(web_app, "_refresh_final_stats", lambda rows: {"provider": "test", "imported": 0, "fetched_rows": 0, "errors": []})
    monkeypatch.setattr(web_app, "_backfill_settled_entry_leg_results", lambda rows: {"entries": 1, "backfilled": 1, "leg_rows": 2, "provider_rows": 2})
    monkeypatch.setattr(web_app, "_auto_check_pending_entries", lambda allow_estimates=False, refresh_providers=True: {"checked": 0, "settled": 0, "entries": []})
    monkeypatch.setattr(
        web_app,
        "_usable_final_stat_for_entry",
        lambda prop, entry: {"actual": 25 if prop["player"] == "A" else 5, "status": "played", "source": "test_final_stats"},
    )
    monkeypatch.setattr(
        web_app.EntryRepository,
        "settle",
        lambda entry_id, result, dnp_legs=0, dnp_mode="reduce", leg_results=None: settled.update({"entry_id": entry_id, "result": result, "legs": leg_results}),
    )

    body = recheck_entry_final_stats()

    assert body["result_review"]["corrected"] == 1
    assert body["result_review"]["entries"][0]["previous_result"] == "Loss"
    assert body["result_review"]["entries"][0]["new_result"] == "Win"
    assert settled["entry_id"] == 21
    assert settled["result"] == "Win"
    assert [leg["result"] for leg in settled["legs"]] == ["Win", "Win"]

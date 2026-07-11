from datetime import datetime
import base64

import web.app as web_app
import services.dashboard as dashboard_service
import data.providers.final_stats as final_stats
import data.providers.espn as espn
import data.providers.sleeper as sleeper
from data.providers.generic_props import normalize_props
import analytics.hit_rate as hit_rate_module
from web.app import (
    EntryPayload,
    EvPayload,
    ParlayChatPayload,
    PropPayload,
    DnpSettingPayload,
    UploadAnalyzePayload,
    AiEntryReviewPayload,
    BankrollTransactionPayload,
    _check_entry_result,
    _calibration_feedback_signals,
    _entry_progress_payload,
    _leg_result,
    _line_movement_payload,
    _parse_betting_history,
    _trending_games_payload,
    analyze_entry,
    analyze_ev,
    backtest,
    dashboard_command_center,
    dashboard_parlay,
    dnp_setting,
    entry_progress,
    ev_scanner,
    health,
    import_final_stats_endpoint,
    optimize_entries,
    place_entry,
    player_hit_rate,
    player_detail,
    classify_default_entry_wagers,
    import_betting_history,
    ai_parlay_chat,
    ai_entry_review,
    ai_status,
    entry_suggestions,
    trending_games,
    line_shop,
    market_timing_alerts,
    clv_report,
    run_sync,
    top_props,
    projection_assist,
    save_bankroll_transaction,
    update_dnp_setting,
    analyze_uploaded_file,
    model_health,
    _stat_from_text,
)
from models.bet import Bet
from web.app import BettingHistoryPayload, FinalStatsPayload, ProjectionAssistPayload
from repository.repositories.entry_repository import EntryRepository
from models.stat_type import StatType


def test_web_health_endpoint():
    assert health() == {"ok": True}


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

    props = normalize_props(payload, "Betr")

    assert props == [
        {
            "projection_id": "betr-0",
            "player": "A",
            "team": "AAA",
            "league": "WNBA",
            "position": "",
            "stat": "Points",
            "line": 20.5,
            "direction": "",
            "game": "BBB",
            "status": "pre_game",
            "trending_count": 999993,
            "rank": 7,
            "image_url": "",
            "platform": "Betr",
        }
    ]


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


def test_ai_parlay_chat_falls_back_when_openai_request_errors(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "NHL", "stat": "Shots on Goal", "line": 2.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "NHL", "stat": "Saves", "line": 28.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "NHL", "stat": "Goals", "line": 0.5, "trending_count": 80000},
    ]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: raw_props)
    monkeypatch.setattr(web_app, "_openai_parlay_response", lambda message, suggestions: (None, "timeout"))

    body = ai_parlay_chat(ParlayChatPayload(message="give me a 3 leg parlay for hockey", platform="PrizePicks", sport="All Sports"))

    assert body["ai_enabled"] is False
    assert body["ai_error"] == "timeout"
    assert body["request"]["sport"] == "NHL"
    assert body["suggestion"]["leg_count"] == 3
    assert "best 3-leg parlay for NHL" in body["message"]


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
    assert body["model"] == "rules-fallback"
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
    assert [suggestion["leg_count"] for suggestion in body["suggestions"][-2:]] == [4, 5]
    assert all(suggestion["risk_tier"] == "Higher Risk" for suggestion in body["suggestions"][-2:])


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
    assert body["legs"][0]["status"] == "Win"


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
    assert body["legs"][0]["progress_percent"] == 87.8
    assert body["legs"][0]["progress_label"] == "Projected 18 / 20.5"


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


def test_entry_progress_endpoint_uses_pending_entries(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])

    body = entry_progress()

    assert body == {"entries": [], "active": 0, "with_live_stats": 0}


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
    monkeypatch.setattr(
        dashboard_service.BankrollTransactionRepository,
        "summary",
        lambda: {"deposits": 0.0, "withdrawals": 0.0, "net": 0.0, "count": 0, "transactions": []},
    )

    body = dashboard_service.get_dashboard()

    assert body["by_sport"]["WNBA"]["bets"] == 1
    assert body["by_sport"]["WNBA"]["entries"] == 1
    assert body["by_sport"]["WNBA"]["wins"] == 1
    assert body["by_sport"]["WNBA"]["losses"] == 1
    assert body["by_sport"]["WNBA"]["profit"] == -1.0
    assert body["performance_insights"]


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

from datetime import datetime
import base64

import web.app as web_app
import data.providers.final_stats as final_stats
import data.providers.espn as espn
import data.providers.sleeper as sleeper
from data.providers.generic_props import normalize_props
import analytics.hit_rate as hit_rate_module
from web.app import (
    EntryPayload,
    EvPayload,
    ParlayChatPayload,
    DnpSettingPayload,
    UploadAnalyzePayload,
    AiEntryReviewPayload,
    _check_entry_result,
    _entry_progress_payload,
    _line_movement_payload,
    _parse_betting_history,
    _trending_games_payload,
    analyze_entry,
    analyze_ev,
    backtest,
    dashboard_parlay,
    dnp_setting,
    entry_progress,
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
    trending_games,
    top_props,
    projection_assist,
    update_dnp_setting,
    analyze_uploaded_file,
)
from models.bet import Bet
from web.app import BettingHistoryPayload, FinalStatsPayload, ProjectionAssistPayload
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
    assert body["legs"][0]["status"] == "Win"


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

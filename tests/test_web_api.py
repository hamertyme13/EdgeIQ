import base64
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import analytics.hit_rate as hit_rate_module
import data.providers.espn as espn
import data.providers.final_stats as final_stats
import data.providers.nba_summer_league as nba_summer_league
import data.providers.sleeper as sleeper
import services.dashboard as dashboard_service
import web.app as web_app
from data.providers.generic_props import normalize_props
from data.providers.prop_filters import is_combined_player_prop
from models.bet import Bet
from models.stat_type import StatType
from repository.bet_repository import BetRepository
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.final_stats_repository import _best_matching_row, _prop_game_date
from utils.time import iso_utc, utc_now
from web.app import (
    AiEntryReviewPayload,
    AlertDeliveryPayload,
    AlertDeliveryTestPayload,
    AutoPaperCalibrationPayload,
    BankrollStrategyPayload,
    BankrollTransactionPayload,
    BettingHistoryPayload,
    DnpSettingPayload,
    EntryPayload,
    EvPayload,
    FinalStatsPayload,
    HedgeCalculatorPayload,
    MiddleCalculatorPayload,
    ParlayChatPayload,
    ProjectionAssistPayload,
    PropPayload,
    ShareSlipPayload,
    UploadAnalyzePayload,
    _calibration_feedback_signals,
    _check_entry_result,
    _entry_progress_payload,
    _leg_result,
    _line_movement_payload,
    _parse_betting_history,
    _parse_parlay_request,
    _stat_from_text,
    _trending_games_payload,
    ai_entry_review,
    ai_parlay_chat,
    ai_status,
    analyze_entry,
    analyze_ev,
    analyze_uploaded_file,
    auto_paper_calibration,
    backfill_entry_final_stats,
    backtest,
    bets,
    classify_default_entry_wagers,
    clv_report,
    confirmed_entry_suggestions,
    confirmed_props,
    daily_briefing,
    dashboard_command_center,
    dashboard_parlay,
    deploy_readiness,
    dnp_setting,
    entry_progress,
    entry_suggestions,
    ev_scanner,
    grading_report,
    health,
    hedge_calculator,
    import_betting_history,
    import_final_stats_endpoint,
    import_wizard,
    line_shop,
    market_timing_alerts,
    middle_calculator,
    model_health,
    optimize_entries,
    place_entry,
    placement_check,
    player_detail,
    player_hit_rate,
    player_research,
    projection_assist,
    recheck_entry_final_stats,
    refresh_calibration_data,
    refresh_portfolio_market_data,
    run_sync,
    save_bankroll_transaction,
    share_entry,
    shared_entry,
    sharp_consensus,
    top_props,
    trending_games,
    update_alert_delivery_settings,
    update_bankroll_strategy,
    update_dnp_setting,
)
from web.app import (
    test_alert_delivery as send_test_alert_delivery,
)


def _verified_rows(rows: list[dict]) -> list[dict]:
    game_time = _today_game_time()
    return [
        {
            **row,
            "game": row.get("game") or f"{row.get('team', 'TEAM')}@OPP",
            "game_time": row.get("game_time") or game_time,
        }
        for row in rows
    ]


def _today_game_time(hour: int = 19) -> str:
    entry_day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    return f"{entry_day}T{hour:02d}:00:00-04:00"


def test_web_health_endpoint():
    assert health() == {"ok": True}


def test_endpoint_timing_snapshot_normalizes_ids_and_flags_slow_routes():
    with web_app._ENDPOINT_TIMING_LOCK:
        web_app._ENDPOINT_TIMINGS.clear()
    web_app._record_endpoint_timing("GET", "/api/entries/42/settle", 1250.0, 200)
    web_app._record_endpoint_timing("GET", "/api/entries/84/settle", 250.0, 500)

    snapshot = web_app._endpoint_timing_snapshot()

    assert snapshot["requests"] == 2
    assert snapshot["slow_requests"] == 1
    assert snapshot["routes"][0]["route"] == "GET /api/entries/{id}/settle"
    assert snapshot["routes"][0]["failures"] == 1


def test_final_stat_recheck_preview_is_read_only(monkeypatch):
    from web.application.settlement_service import recheck_final_stats_preview_payload

    entries = [{"id": 7, "status": "Pending", "props": [{"entry_prop_id": 9, "player": "A"}]}]
    monkeypatch.setattr(EntryRepository, "all", lambda: entries)
    writes = []

    preview = recheck_final_stats_preview_payload(
        entries_needing_refresh=lambda rows: rows,
        preview_leg=lambda entry, prop: {
            "entry_prop_id": prop["entry_prop_id"],
            "player": prop["player"],
            "action": "update_from_local_final",
            "will_change": True,
        },
    )

    assert writes == []
    assert preview["read_only"] is True
    assert preview["local_changes"] == 1
    assert preview["entries_with_local_changes"] == 1


def test_datetime_serialization_marks_naive_db_values_as_utc():
    assert iso_utc(datetime(2026, 7, 10, 4, 10)) == "2026-07-10T04:10:00+00:00"
    assert iso_utc(utc_now()).endswith("+00:00")


def test_generated_entry_day_uses_eastern_calendar_date():
    now = datetime(2026, 8, 2, 2, 0, tzinfo=UTC)

    assert web_app._is_prop_on_entry_day(
        {"game_time": "2026-08-01T23:30:00-04:00"},
        now=now,
    ) is True
    assert web_app._is_prop_on_entry_day(
        {"game_time": "2026-08-02T19:00:00-04:00"},
        now=now,
    ) is False


def test_app_generated_entry_rejects_a_future_slate(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "utc_now",
        lambda: datetime(2026, 8, 2, 14, 0, tzinfo=UTC),
    )
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "entry_mode": "paper",
        "recommended_by_app": True,
        "props": [{
            "player": "Future Player",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "game": "AAA@BBB",
            "game_time": "2026-08-03T19:00:00-04:00",
        }],
    })

    blocks = web_app._generated_entry_day_blocks(payload)

    assert blocks
    assert "today's slate" in blocks[0]


def test_generated_prop_pool_excludes_future_slates(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "utc_now",
        lambda: datetime(2026, 8, 2, 14, 0, tzinfo=UTC),
    )
    props = [
        {
            "player": "Today Player",
            "platform": "PrizePicks",
            "game_time": "2026-08-02T19:00:00-04:00",
        },
        {
            "player": "Tomorrow Player",
            "platform": "PrizePicks",
            "game_time": "2026-08-03T19:00:00-04:00",
        },
    ]

    pools = web_app._props_by_platform_from_props("PrizePicks", props)

    assert [prop["player"] for prop in pools[0][1]] == ["Today Player"]


def test_automatic_final_refresh_only_includes_due_recent_games(monkeypatch):
    monkeypatch.setattr(web_app, "_supports_automatic_final_stat", lambda prop: True)
    now = datetime(2026, 7, 28, 18, 0, tzinfo=UTC)
    entries = [{
        "id": 1,
        "props": [
            {"player": "Due", "sport": "WNBA", "game_time": "2026-07-28T12:00:00Z"},
            {"player": "Scheduled", "sport": "WNBA", "game_time": "2026-07-28T20:00:00Z"},
            {"player": "Expired", "sport": "WNBA", "game_time": "2026-07-27T12:00:00Z"},
            {
                "player": "Final",
                "sport": "WNBA",
                "game_time": "2026-07-28T12:00:00Z",
                "actual": 20.0,
                "final_status": "played",
            },
        ],
    }]

    due = web_app._entries_due_for_automatic_final_refresh(entries, now=now)

    assert [prop["player"] for prop in due[0]["props"]] == ["Due"]


def test_settlement_audit_blocks_expired_automatic_retry(monkeypatch):
    recorded = {}
    monkeypatch.setattr(web_app, "_supports_automatic_final_stat", lambda prop: True)
    monkeypatch.setattr(
        web_app.SettlementAuditRepository,
        "record",
        lambda payload: recorded.update(payload),
    )
    monkeypatch.setattr(
        web_app,
        "utc_now",
        lambda: datetime(2026, 7, 28, 18, 0, tzinfo=UTC),
    )

    web_app._record_settlement_audit(
        {"id": 8},
        {
            "entry_prop_id": 9,
            "player": "A",
            "sport": "WNBA",
            "stat": "Points",
            "line": 10.5,
            "game_time": "2026-07-27T12:00:00Z",
        },
        None,
        None,
        "Unknown",
        "unmatched",
        "unknown",
    )

    assert recorded["status"] == "blocked"
    assert recorded["reason_code"] == "official_final_retry_window_expired"
    assert "Automatic retries stopped" in recorded["message"]


def test_settlement_audit_labels_future_games_scheduled(monkeypatch):
    recorded = {}
    monkeypatch.setattr(web_app, "_supports_automatic_final_stat", lambda prop: True)
    monkeypatch.setattr(
        web_app.SettlementAuditRepository,
        "record",
        lambda payload: recorded.update(payload),
    )
    monkeypatch.setattr(
        web_app,
        "utc_now",
        lambda: datetime(2026, 7, 28, 18, 0, tzinfo=UTC),
    )

    web_app._record_settlement_audit(
        {"id": 8},
        {
            "entry_prop_id": 9,
            "player": "A",
            "sport": "WNBA",
            "stat": "Points",
            "line": 10.5,
            "game_time": "2026-07-29T00:00:00Z",
        },
        None,
        None,
        "Unknown",
        "unmatched",
        "unknown",
    )

    assert recorded["status"] == "scheduled"
    assert recorded["reason_code"] == "game_not_started"
    assert "has not started" in recorded["message"]


def test_entry_progress_does_not_refresh_providers_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(
        web_app,
        "_auto_check_pending_entries",
        lambda allow_estimates, refresh_providers: calls.append(refresh_providers) or {
            "checked": 0,
            "settled": 0,
        },
    )

    entry_progress(auto_check=True)

    assert calls == [False]


def test_pending_serializer_excludes_heavy_audit_fields():
    serialized = web_app._serialize_pending({
        "id": 4,
        "platform": "PrizePicks",
        "entry_mode": "paper",
        "wager": 0.0,
        "multiplier": 3.0,
        "potential_payout": 0.0,
        "placed_at": datetime(2026, 7, 28, tzinfo=UTC),
        "audit_snapshot": "large internal snapshot",
        "props": [{
            "player": "A",
            "direction": "Over",
            "stat": "Points",
            "line": 10.5,
            "projection": 12.0,
            "data_quality": {"large": "payload"},
        }],
    })

    assert "audit_snapshot" not in serialized
    assert serialized["props"] == [{
        "player": "A",
        "direction": "Over",
        "stat": "Points",
        "line": 10.5,
    }]


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


def test_dashboard_command_center_reuses_recent_analyzed_slate(monkeypatch):
    calls = []
    web_app._COMMAND_CENTER_CACHE.clear()
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])
    monkeypatch.setattr(web_app, "_command_center_payload", lambda platform, sport: calls.append((platform, sport)) or {"cards": []})

    first = dashboard_command_center("PrizePicks", "WNBA")
    second = dashboard_command_center("PrizePicks", "WNBA")

    assert first == second == {"cards": []}
    assert calls == [("PrizePicks", "WNBA")]


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
            {"player": "A", "sport": "WNBA", "stat": "Points", "direction": "Over", "line": 20.5, "confidence": 64, "edge": 1.2, "platform": "PrizePicks", "forecast_paid_eligible": True},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "direction": "Under", "line": 6.5, "confidence": 61, "edge": 0.8, "platform": "PrizePicks", "forecast_paid_eligible": True},
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
    monkeypatch.setattr(web_app, "_command_center_payload", lambda platform, sport, **kwargs: {
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
    monkeypatch.setattr(web_app, "_confirmed_props_payload", lambda platform, sport, limit=80, **kwargs: {
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
    monkeypatch.setattr(web_app, "_daily_paper_cards", lambda platform, sport, stats, model_health=None: [{
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


def test_daily_top_opportunities_excludes_premium_adjusted_lines_and_preserves_proof(monkeypatch) -> None:
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(
        web_app.sportsbook_odds,
        "get_player_prop_consensus",
        lambda *args, **kwargs: {
            "configured": True,
            "available": True,
            "source": "The Odds API",
            "market_probability": 55.0,
            "book_count": 4,
            "quality": "strong",
            "dfs_offers": [{"platform": "PrizePicks"}],
            "reason": "Median no-vig probability from 4 sportsbooks.",
            "payout_note": "Live DFS payout evidence matched.",
        },
    )
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [
        {"line": 19.5, "recorded_at": datetime(2026, 7, 29, 10, 0, tzinfo=UTC)},
        {"line": 20.5, "recorded_at": datetime(2026, 7, 29, 11, 0, tzinfo=UTC)},
    ])
    command = {
        "cards": [{
            "props": [
                {
                    "player": "Premium Player",
                    "sport": "WNBA",
                    "stat": "Points",
                    "direction": "Under",
                    "line": 39.5,
                    "standard_line": 18.5,
                    "confidence": 98,
                    "edge": 20,
                    "line_offer_type": "demon",
                    "adjusted_line": True,
                    "is_premium_line": True,
                },
                {
                    "player": "Standard Player",
                    "sport": "WNBA",
                    "stat": "Points",
                    "direction": "Over",
                    "line": 20.5,
                    "projection": 22.0,
                    "confidence": 64,
                    "edge": 1.2,
                    "line_offer_type": "standard",
                    "team": "AAA",
                    "game": "AAA@BBB",
                    "game_time": "2026-07-30T00:00:00Z",
                    "platform": "PrizePicks",
                    "forecast_snapshot": {"source": "verified_history_distribution"},
                    "forecast_paid_eligible": True,
                    "end_to_end_confirmed": True,
                },
            ],
        }],
    }

    rows = web_app._daily_top_opportunities(command, {"props": []})

    assert [row["player"] for row in rows] == ["Standard Player"]
    assert rows[0]["confidence"] <= 64
    assert rows[0]["team"] == "AAA"
    assert rows[0]["game_time"] == "2026-07-30T00:00:00Z"
    assert rows[0]["projection"] == 22.0
    assert rows[0]["forecast_paid_eligible"] is True
    assert rows[0]["decision_receipt"]["movement"]["change"] == 1.0
    assert rows[0]["decision_receipt"]["market_probability"] == 55.0
    assert rows[0]["decision_receipt"]["market_book_count"] == 4
    assert rows[0]["decision_receipt"]["model_market_edge"] == 3.0
    assert rows[0]["decision_receipt"]["portfolio_exposure"]["same_market_entries"] == 0
    assert any(label["label"] == "Market verified · 4 books" for label in rows[0]["data_strength"])


def test_daily_paper_cards_skip_generation_while_samples_are_pending(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "backtest_summary",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("backtest should not run")),
    )

    cards = web_app._daily_paper_cards(
        "PrizePicks",
        "WNBA",
        {"entries": {"paper": {"pending": 3}}},
    )

    assert len(cards) == 1
    assert cards[0]["type"] == "paper_status"
    assert "skipped duplicate sample generation" in cards[0]["reason"]


def test_daily_opportunities_only_request_market_odds_for_visible_top_five(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app.sportsbook_odds,
        "get_player_prop_consensus",
        lambda player, *args, **kwargs: calls.append(player) or {
            "available": False,
            "book_count": 0,
            "reason": "No exact-line market.",
            "dfs_offers": [],
        },
    )
    props = [
        {
            "player": f"Player {index}",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "direction": "Over",
            "line": 10.5 + index,
            "confidence": 50 + index,
            "edge": index / 10,
            "game": "AAA@BBB",
            "platform": "PrizePicks",
        }
        for index in range(8)
    ]

    rows = web_app._daily_top_opportunities({"cards": [{"props": props}]}, {"props": []})

    assert len(rows) == 5
    assert len(calls) == 5
    assert set(calls) == {row["player"] for row in rows}


def test_pending_portfolio_exposure_blocks_duplicate_paid_market(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [{
        "id": 7,
        "entry_mode": "real",
        "wager": 10,
        "props": [{
            "player": "A",
            "stat": "Points",
            "direction": "Over",
            "game": "AAA@BBB",
        }],
    }])
    entry = web_app._entry_from_payload(EntryPayload.model_validate({
        "platform": "PrizePicks",
        "entry_mode": "real",
        "wager": 5,
        "props": [{
            "player": "A",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "direction": "Over",
            "line": 20.5,
            "game": "AAA@BBB",
        }],
    }))

    flags = web_app._pending_portfolio_exposure_flags(entry)

    assert any(flag["severity"] == "danger" for flag in flags)
    assert any("Duplicate pending market exposure" in flag["message"] for flag in flags)


def test_market_consensus_guardrails_block_missing_or_thin_paid_evidence():
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "entry_mode": "real",
        "recommended_by_app": True,
        "props": [
            {
                "player": "A",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "direction": "Over",
                "confidence": 78,
            },
            {
                "player": "B",
                "sport": "WNBA",
                "stat": "Assists",
                "line": 6.5,
                "direction": "Under",
                "confidence": 76,
            },
        ],
    })
    entry = web_app._entry_from_payload(payload)
    platform_value = {
        "legs": [
            {
                "player": "A",
                "stat": "Points",
                "market_consensus": {
                    "available": True,
                    "book_count": 1,
                    "market_probability": 10,
                },
            },
            {
                "player": "B",
                "stat": "Assists",
                "market_consensus": {"available": False},
            },
        ],
    }

    flags = web_app._market_consensus_guardrails(entry, platform_value, payload)

    assert any("at least 2" in flag["message"] and flag["severity"] == "danger" for flag in flags)
    assert any("no exact-line multi-book probability" in flag["message"] for flag in flags)
    assert any("model and no-vig market differ" in flag["message"] for flag in flags)


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
    assert "Daily Briefing could not finish" in scan["errors"][0]
    assert status["runs"][0]["status"] == "failed"


def test_daily_games_today_deduplicates_reversed_matchups(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_player_availability_payload",
        lambda player, sport, team, game: {"player": player, "status": "available", "availability_score": 100},
    )
    confirmed = {
        "props": [
            {
                "player": "A",
                "team": "NYL",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "confidence": 62,
                "edge": 1.0,
                "game": "LVA",
            },
            {
                "player": "B",
                "team": "LVA",
                "sport": "WNBA",
                "stat": "Assists",
                "line": 6.5,
                "confidence": 60,
                "edge": 0.8,
                "game": "NYL",
            },
        ],
    }

    games = web_app._daily_games_today("PrizePicks", "WNBA", confirmed)

    assert len(games) == 1
    assert games[0]["prop_count"] == 2
    assert games[0]["matchup_label"] == "NYL vs LVA"


def test_interrupted_daily_briefing_scan_is_recovered(monkeypatch):
    interrupted = web_app._new_daily_scan("PrizePicks", "WNBA", trigger="manual")
    interrupted = {**interrupted, "status": "building_entries", "progress": 70}
    monkeypatch.setattr(
        web_app.SettingsRepository,
        "get",
        lambda key, default="": json.dumps(interrupted) if key == web_app.DAILY_SCAN_STATUS_KEY else default,
    )
    saved = []
    monkeypatch.setattr(web_app, "_save_daily_scan_status", lambda scan: saved.append(scan) or scan)

    web_app._recover_interrupted_daily_scan()

    assert saved[0]["status"] == "not_run_today"
    assert saved[0]["progress"] == 0
    assert "interrupted" in saved[0]["message"].lower()


def test_entry_suggestions_limit_both_to_entry_platforms(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [{
        "player": f"{platform} Player",
        "team": "AAA",
        "league": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "platform": platform,
        "game_time": _today_game_time(),
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


def test_underdog_generator_supports_eight_legs(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [{
        "player": "A",
        "team": "AAA",
        "league": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "platform": platform,
        "game_time": _today_game_time(),
    }])

    def fake_suggest_entries(*args, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(web_app, "suggest_entries", fake_suggest_entries)

    body = entry_suggestions(
        sport="WNBA",
        platform="Underdog",
        leg_count=8,
        avoid="playera|points|over|20.50",
    )

    assert body["platform"] == "Underdog"
    assert body["leg_count"] == 8
    assert body["maximum_legs"] == 8
    assert calls[0]["leg_count"] == 8
    assert calls[0]["apply_feedback"] is True
    assert calls[0]["diversify"] is True
    assert calls[0]["avoid_prop_keys"] == {"playera|points|over|20.50"}


def test_nfl_entry_suggestions_explain_when_same_day_lines_are_unavailable(monkeypatch):
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])

    body = entry_suggestions(sport="NFL", platform="Both", leg_count=3)

    assert body["mode"] == "waiting_for_nfl_lines"
    assert body["suggestions"] == []
    assert "same-day" in body["message"]
    assert "confirmed matchup and kickoff" in body["message"]


@pytest.mark.parametrize(
    "stat",
    [
        "Passing Yds",
        "Rushing Yds",
        "Receiving Yds",
        "Rush + Rec Yards",
        "XP Made",
        "Tackles + Assists",
    ],
)
def test_nfl_settlement_accepts_provider_stat_abbreviations(stat):
    eligibility = web_app._end_to_end_prop_eligibility({
        "player": "NFL Player",
        "team": "NE",
        "sport": "NFL",
        "stat": stat,
        "game": "NE@NYG",
        "game_time": "2026-08-07T23:00:00Z",
    })

    assert eligibility["eligible"] is True


def test_live_nfl_provider_snapshot_uses_official_schedule_after_market_closes(monkeypatch):
    now = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    monkeypatch.setattr(web_app, "utc_now", lambda: now)
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    monkeypatch.setattr(web_app, "fetch_game_times", lambda sport, game_date: [{
        "sport": "NFL",
        "game": "NE@NYG",
        "game_time": "2026-08-07T00:00:00Z",
        "source": "espn",
    }])
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "entry_mode": "real",
        "recommended_by_app": True,
        "wager": 10,
        "props": [{
            "player": "NFL Player",
            "provider_player_id": "nfl-42",
            "player_provider": "Underdog",
            "team": "NE",
            "sport": "NFL",
            "stat": "Passing Yds",
            "line": 188.5,
            "game": "NYG",
            "platform": "Underdog",
        }],
    })

    blocks = web_app._end_to_end_placement_blocks(payload)

    assert blocks == []
    assert payload.props[0].game == "NE@NYG"
    assert payload.props[0].game_time == "2026-08-07T00:00:00Z"


def test_live_nfl_market_uses_official_kickoff_when_provider_time_is_missing(monkeypatch):
    now = datetime(2026, 8, 7, 1, 30, tzinfo=UTC)
    monkeypatch.setattr(web_app, "utc_now", lambda: now)
    monkeypatch.setattr(web_app, "fetch_game_times", lambda sport, game_date: [{
        "sport": "NFL",
        "game": "NE@NYG",
        "game_time": "2026-08-07T00:00:00Z",
        "source": "espn",
    }])
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "entry_mode": "real",
        "recommended_by_app": True,
        "wager": 10,
        "props": [{
            "player": "NFL Defender",
            "provider_player_id": "nfl-99",
            "player_provider": "Underdog",
            "team": "NE",
            "sport": "NFL",
            "stat": "Tackles + Assists",
            "line": 4.5,
            "game": "NYG",
            "platform": "Underdog",
        }],
    })
    current = [{
        "player": "NFL Defender",
        "player_id": "nfl-99",
        "team": "NE",
        "league": "NFL",
        "stat": "Tackles + Assists",
        "line": 4.5,
        "game": "NYG",
        "game_time": "",
        "platform": "Underdog",
    }]

    context = web_app._hydrate_payload_prop_context(payload.props[0], "Underdog", current)

    assert context is not None
    assert payload.props[0].game == "NE@NYG"
    assert payload.props[0].game_time == "2026-08-07T00:00:00Z"


def test_standard_prop_with_projection_below_line_recommends_under(monkeypatch):
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "_versioned_calibration_rows", lambda: [])

    analyzed = web_app._analyzed_feed_prop({
        "player": "NFL Player",
        "team": "NE",
        "league": "NFL",
        "stat": "Receiving Yards",
        "line": 60.5,
        "projection": 54.0,
        "platform": "Underdog",
        "line_offer_type": "standard",
        "game": "NE@NYG",
        "game_time": "2026-08-07T23:00:00Z",
    })

    assert analyzed["direction"] == "Under"
    assert analyzed["edge"] == 6.5


def test_advantage_center_watchlist_boost_and_game_context(monkeypatch):
    props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA-BBB", "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 21.5, "game": "BBB-AAA", "trending_count": 90000, "platform": "Underdog"},
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
    assert len(body["game_contexts"]) == 2
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
    assert "api_usage" in health_body
    assert "requests_avoided" in health_body["api_usage"]
    sleeper_health = next(provider for provider in health_body["providers"] if provider["name"] == "Sleeper")
    assert "api_usage" in sleeper_health
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
    assert all(prop["projection"] == prop["line"] for prop in props)
    assert all(prop["projection_source"] == "market_prior" for prop in props)
    assert all(prop["forecast_paid_eligible"] is False for prop in props)


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
    assert first["projection_source"] == "market_prior"
    assert first["projection"] == 20.0
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
        lambda player, stat, platform, **kwargs: [{"line": 19.5, "recorded_at": datetime(2026, 7, 8, 12, 0)}],
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
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: _verified_rows(raw_props))

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
                "game": "SP@OPP",
                "game_time": "2026-07-20T19:00:00Z",
                "trending_count": 10,
            }
        ],
    )

    props = web_app._fetch_props("Sleeper", "WNBA")

    assert props[0]["platform"] == "Sleeper"
    assert props[0]["player"] == "Sleeper Player"


def test_provider_board_only_keeps_end_to_end_gradable_props():
    rows = _verified_rows([
        {"player": "WNBA Player", "team": "AAA", "league": "WNBA", "stat": "PRA", "line": 30.5},
        {"player": "NFL Player", "team": "BBB", "league": "NFL", "stat": "Receiving Yards", "line": 45.5},
        {"player": "MLB Hitter", "team": "CCC", "league": "MLB", "position": "OF", "stat": "Points", "line": 6.5},
        {"player": "MLB Pitcher", "team": "DDD", "league": "MLB", "position": "SP", "stat": "Points", "line": 35.5},
        {"player": "Unsupported Hitter", "team": "EEE", "league": "MLB", "position": "1B", "stat": "Total Bases", "line": 1.5},
    ])

    props = web_app._fetch_platform_props_uncached("PrizePicks", lambda: rows)

    assert {prop["player"] for prop in props} == {"WNBA Player", "NFL Player", "MLB Pitcher"}
    assert all(web_app._end_to_end_prop_eligibility(prop)["eligible"] for prop in props)


def test_nfl_end_to_end_eligibility_accepts_full_game_markets_only():
    base = {
        "player": "NFL Player",
        "team": "ARI",
        "league": "NFL",
        "game": "ARI @ CAR",
        "game_time": "2026-08-06T20:00:00-04:00",
    }

    for stat in ("Pass Yards", "Rush Yards", "Rec Yards", "Rush + Rec TDs", "INTs Thrown", "Sacks"):
        assert web_app._end_to_end_prop_eligibility({**base, "stat": stat})["eligible"] is True

    for stat in ("1Q Pass Yards", "1H Rush Yards", "First TD Scorer", "Fantasy Points"):
        result = web_app._end_to_end_prop_eligibility({**base, "stat": stat})
        assert result["eligible"] is False
        assert result["reasons"]


def test_end_to_end_eligibility_requires_matchup_and_valid_start_time():
    eligibility = web_app._end_to_end_prop_eligibility({
        "player": "A",
        "team": "AAA",
        "league": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "game_time": "not-a-date",
    })

    assert eligibility["eligible"] is False
    assert "matchup is missing" in eligibility["reasons"]
    assert "confirmed game time is missing" in eligibility["reasons"]


def test_espn_refresh_uses_eastern_scheduled_game_date_over_placement_date():
    dates = espn._entry_dates([{
        "placed_at": datetime(2026, 7, 18),
        "props": [{"game_time": "2026-07-21T01:00:00Z"}],
    }])

    assert [day.isoformat() for day in dates] == ["2026-07-20"]


def test_stale_unverifiable_paper_entry_is_removed_from_pending_calibration(monkeypatch):
    excluded = []
    monkeypatch.setattr(web_app.EntryRepository, "exclude_from_tracking", lambda entry_id, reason: excluded.append((entry_id, reason)))
    entries = [{
        "id": 91,
        "entry_mode": "paper",
        "placed_at": datetime(2026, 7, 10),
        "props": [{
            "player": "Legacy Player",
            "team": "AAA",
            "sport": "NFL",
            "stat": "First TD Scorer",
            "line": 45.5,
            "game": "AAA@BBB",
            "game_time": "2026-07-10T19:00:00Z",
        }],
    }]

    count = web_app._exclude_stale_unverifiable_paper_entries(entries)

    assert count == 1
    assert excluded[0][0] == 91
    assert "excluded from calibration" in excluded[0][1]


def test_expired_unresolved_paper_entry_is_excluded_without_grading(monkeypatch):
    excluded = []
    monkeypatch.setattr(web_app.EntryRepository, "exclude_from_tracking", lambda entry_id, reason: excluded.append((entry_id, reason)))
    entries = [{
        "id": 92,
        "entry_mode": "paper",
        "props": [
            {
                "player": "Verified Player",
                "actual": 14.0,
                "final_status": "played",
                "game_time": "2026-07-10T19:00:00Z",
            },
            {
                "player": "Missing Player",
                "actual": None,
                "final_status": "unknown",
                "game_time": "2026-07-10T19:00:00Z",
            },
        ],
    }]

    count = web_app._exclude_expired_unresolved_paper_entries(entries)

    assert count == 1
    assert excluded[0][0] == 92
    assert "instead of assigning a result" in excluded[0][1]


def test_mismatched_settlement_evidence_is_quarantined(monkeypatch):
    quarantined = []
    monkeypatch.setattr(
        web_app.SettlementAuditRepository,
        "game_date_mismatches",
        lambda: [
            {"entry_id": 7, "entry_prop_id": 21},
            {"entry_id": 7, "entry_prop_id": 22},
        ],
    )
    monkeypatch.setattr(
        web_app.PredictionLedgerRepository,
        "quarantine_entry_props",
        lambda ids: quarantined.extend(ids) or len(ids),
    )

    result = web_app._quarantine_mismatched_settlement_evidence()

    assert result["detected"] == 2
    assert result["quarantined"] == 2
    assert result["entries"] == 1
    assert quarantined == [21, 22]


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


def test_payout_analysis_endpoint_does_not_load_provider_context(monkeypatch):
    monkeypatch.setattr(web_app, "_entry_from_payload", lambda payload: (_ for _ in ()).throw(AssertionError("full analysis should not run")))
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "multiplier": 6.5,
        "payout_type": "standard",
        "entry_mode": "paper",
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "line": 20.5, "confidence": 60},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "line": 5.5, "confidence": 60},
            {"player": "C", "sport": "WNBA", "stat": "Rebounds", "line": 8.5, "confidence": 60},
        ],
    })

    result = web_app.entry_payout_analysis(payload)

    assert result["platform"] == "Underdog"
    assert result["displayed_multiplier"] == 6.5
    assert result["expected_value"] > 0


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


def test_uploaded_screenshot_uses_local_ocr_without_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        web_app,
        "_local_extract_props_from_image",
        lambda raw, file_name, source: {
            "platform": "Underdog",
            "ocr_text": "Kelsey Mitchell\nPts + Rebs + Asts\n19.5\nHigher",
            "props": [{
                "player": "Kelsey Mitchell",
                "team": "IND",
                "league": "WNBA",
                "stat": "Pts + Rebs + Asts",
                "line": 19.5,
                "direction": "Over",
                "platform": "Underdog",
                "game": "IND @ SEA",
                "game_time": "2026-07-29T01:30:00Z",
                "provider_backed": True,
            }],
        },
    )

    body = analyze_uploaded_file(
        UploadAnalyzePayload(
            file_name="slip.png",
            mime_type="image/png",
            target="entry",
            source="Underdog",
            content_base64=base64.b64encode(b"\x89PNG\r\n\x1a\nlocal-test").decode("utf-8"),
        )
    )

    assert body["ai_enabled"] is False
    assert body["local_ocr"] is True
    assert body["prop_count"] == 1
    assert body["props"][0]["player"] == "Kelsey Mitchell"
    assert body["props"][0]["game_time"] == "2026-07-29T01:30:00Z"


def test_local_ocr_matches_line_and_direction_inside_each_player_block(monkeypatch):
    active = [
        {"player": "Player Alpha", "league": "WNBA", "stat": "Points", "line": 20.5, "platform": "PrizePicks"},
        {"player": "Player Alpha", "league": "WNBA", "stat": "Assists", "line": 6.5, "platform": "PrizePicks"},
        {"player": "Player Beta", "league": "WNBA", "stat": "Assists", "line": 6.5, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: active)
    text = "\n".join([
        "Player Alpha",
        "Points",
        "20.5",
        "Higher",
        "Player Beta",
        "Assists",
        "6.5",
        "Lower",
    ])

    props = web_app._match_ocr_text_to_live_props(text, "PrizePicks")

    assert [(prop["player"], prop["stat"], prop["direction"]) for prop in props] == [
        ("Player Alpha", "Points", "Over"),
        ("Player Beta", "Assists", "Under"),
    ]


def test_screenshot_props_are_provider_verified_and_deduplicated(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_openai_extract_props_from_image",
        lambda raw, mime_type: {
            "platform": "PrizePicks",
            "props": [
                {"player": "A", "sport": "WNBA", "stat": "PRA", "line": 21.5, "direction": "Over"},
                {"player": "A", "sport": "WNBA", "stat": "Pts + Rebs + Asts", "line": 21.5, "direction": "Higher"},
                {"player": "B", "sport": "WNBA", "stat": "Points", "line": 15.5},
            ],
        },
    )
    monkeypatch.setattr(
        web_app,
        "_fetch_props",
        lambda platform, sport: [
            {
                "player": "A",
                "team": "AAA",
                "league": "WNBA",
                "stat": "Points + Rebounds + Assists",
                "line": 21.5,
                "platform": "PrizePicks",
                "game": "AAA@BBB",
                "game_time": "2026-08-01T23:00:00Z",
            },
            {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Points", "line": 15.5, "platform": "PrizePicks"},
        ],
    )

    body = analyze_uploaded_file(
        UploadAnalyzePayload(
            file_name="slip.png",
            mime_type="image/png",
            target="entry",
            source="PrizePicks",
            content_base64=base64.b64encode(b"fake-image").decode("utf-8"),
        )
    )

    assert body["prop_count"] == 1
    assert body["duplicates_removed"] == 1
    assert body["rejected_unverified"] == 1
    assert body["props"][0]["stat"] == "Points + Rebounds + Assists"
    assert body["props"][0]["provider_backed"] is True


def test_screenshot_review_requires_selected_verified_picks():
    source = Path(web_app.__file__).with_name("static").joinpath("app.js").read_text(encoding="utf-8")

    assert 'data-upload-prop-index="${index}"' in source
    assert "Load Selected Picks" in source
    assert "uniqueUploadedProps(props)" in source
    assert "prop.direction || \"Over\"" not in source[source.index("function renderUploadResult"):source.index("function fileToBase64")]


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

    assert signals == []


def test_web_dashboard_parlay_serializes_three_legs(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@OPP", "game_time": _today_game_time(19), "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "game": "BBB@OPP", "game_time": _today_game_time(20), "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "game": "CCC@OPP", "game_time": _today_game_time(21), "trending_count": 80000},
    ]
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))

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
                    "game": "DAL@OPP",
                    "game_time": "2026-07-14T19:00:00-04:00",
            },
        ],
    )

    props = web_app._fetch_props("Underdog", None)

    assert [prop["player"] for prop in props] == ["Paige Bueckers"]


def test_placement_check_flags_missing_time_and_changed_line(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 100.0, "monthly_profit": 0.0})
    monkeypatch.setattr(web_app, "fetch_game_times", lambda sport, game_date: [])
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

    assert body["ok"] is False
    assert body["requires_confirmation"] is True
    assert any("game time is unavailable" in warning for warning in body["warnings"])
    assert any("closest active line is 21.5" in warning for warning in body["warnings"])
    assert any("matchup is missing" in warning for warning in body["warnings"])
    assert any("manual final-stat verification" in warning for warning in body["warnings"])
    assert body["audit"]["status"] == "blocked"
    assert any(item["label"] == "Open exposure" for item in body["audit"]["items"])


def test_placement_check_blocks_unproven_app_recommended_real_entry(monkeypatch):
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    monkeypatch.setattr(web_app, "_platform_value_check", lambda payload: {})
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": False})
    monkeypatch.setattr(web_app, "_loss_protection_entry_flags", lambda entry, payload: [])

    raw = {
        "platform": "PrizePicks",
        "wager": 5,
        "entry_mode": "real",
        "recommended_by_app": True,
        "props": [{
            "player": "A",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "projection": 22.0,
            "projection_source": "line_model",
            "auto_projected": True,
        }],
    }

    body = placement_check(EntryPayload.model_validate(raw))

    assert any("versioned forecast and segment-calibration evidence" in block for block in body["blocks"])
    assert any("matchup is missing" in block for block in body["blocks"])


def test_placement_check_blocks_unproven_manual_real_entry(monkeypatch):
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    monkeypatch.setattr(web_app, "_platform_value_check", lambda payload: {})
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": False})
    monkeypatch.setattr(web_app, "_loss_protection_entry_flags", lambda entry, payload: [])

    raw = {
        "platform": "PrizePicks",
        "wager": 5,
        "entry_mode": "real",
        "props": [{
            "player": "A",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "projection": 22.0,
            "projection_source": "line_model",
            "auto_projected": True,
        }],
    }

    body = placement_check(EntryPayload.model_validate(raw))

    assert any("versioned forecast and segment-calibration evidence" in block for block in body["blocks"])
    assert any("not available in the current PrizePicks feed" in warning for warning in body["warnings"])
    assert any("current provider board" in block for block in body["blocks"])


def test_placement_check_explains_when_selected_platform_lacks_player_stat(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 100.0, "monthly_profit": 0.0})
    monkeypatch.setattr(web_app, "_platform_value_check", lambda payload: {})
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": False})
    monkeypatch.setattr(web_app, "_loss_protection_entry_flags", lambda entry, payload: [])
    monkeypatch.setattr(
        web_app,
        "_fetch_platform_props",
        lambda platform: [{
            "player": "Kelsey Mitchell",
            "team": "IND",
            "league": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "platform": platform,
            "game": "IND @ SEA",
            "game_time": "2026-07-29T01:30:00Z",
        }],
    )
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "entry_mode": "real",
        "wager": 5,
        "recommended_by_app": True,
        "props": [{
            "player": "Kelsey Mitchell",
            "team": "IND",
            "sport": "WNBA",
            "stat": "Points + Rebounds + Assists",
            "line": 19.5,
        }],
    })

    body = placement_check(payload)

    assert body["ok"] is False
    assert any(
        "Underdog currently lists Kelsey Mitchell, but does not offer a Points + Rebounds + Assists market"
        in block
        for block in body["blocks"]
    )


def test_underdog_abbreviated_pra_is_end_to_end_eligible() -> None:
    result = web_app._end_to_end_prop_eligibility({
        "player": "Kelsey Mitchell",
        "team": "IND",
        "league": "WNBA",
        "stat": "Pts + Rebs + Asts",
        "line": 19.5,
        "game": "IND @ SEA",
        "game_time": "2026-07-29T01:30:00Z",
        "platform": "Underdog",
    })

    assert result["eligible"] is True
    assert result["stat"] == "points rebounds assists"


def test_placement_check_allows_auto_projection_for_paper_mode(monkeypatch):
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    monkeypatch.setattr(web_app, "_platform_value_check", lambda payload: {})
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": False})
    monkeypatch.setattr(web_app, "_loss_protection_entry_flags", lambda entry, payload: [])
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "entry_mode": "paper",
        "props": [{
            "player": "A",
            "team": "AAA",
            "sport": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "projection": 22.0,
            "projection_source": "line_model",
            "auto_projected": True,
        }],
    })

    body = placement_check(payload)

    assert not any("provider-backed projections" in block for block in body["blocks"])
    assert body["ok"] is True
    assert any("manual final-stat verification" in warning for warning in body["warnings"])


def test_line_snapshots_keep_game_and_offer_provenance(monkeypatch):
    saved = []
    monkeypatch.setattr(web_app.LineHistoryRepository, "record_many", lambda rows: saved.extend(rows))

    web_app._record_line_snapshots([{
        "player": "Azurá Stevens",
        "stat": "Points",
        "platform": "Underdog",
        "line": 12.5,
        "game": "LAS @ CHI",
        "game_time": "2026-07-22T20:00:00Z",
        "line_offer_type": "standard",
    }])

    assert saved[0]["game"] == "LAS @ CHI"
    assert saved[0]["game_time"] == "2026-07-22T20:00:00Z"
    assert saved[0]["line_offer_type"] == "standard"


def test_placement_check_blocks_when_open_exposure_cap_is_exceeded(monkeypatch):
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [
        {"entry_mode": "real", "wager": 14.0},
        {"entry_mode": "paper", "wager": 100.0},
    ])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 100.0, "monthly_profit": 0.0})
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": json.dumps({
        "max_open_exposure_pct": 15,
        "max_wager_pct": 10,
        "stop_loss_pct": 12,
    }) if key == "bankroll_strategy" else default)

    body = placement_check(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "wager": 5,
                "multiplier": 3,
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "platform": "PrizePicks"},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "platform": "PrizePicks"},
                ],
            }
        )
    )

    assert body["ok"] is False
    assert body["audit"]["status"] == "blocked"
    assert any("Open exposure" in block for block in body["blocks"])


def test_bankroll_strategy_round_trips_guardrails(monkeypatch):
    store = {}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))

    body = update_bankroll_strategy(
        BankrollStrategyPayload(
            mode="conservative",
            unit_size=8,
            max_wager_pct=3,
            max_open_exposure_pct=9,
            stop_loss_pct=6,
            paper_first=True,
        )
    )

    assert body["strategy"]["max_open_exposure_pct"] == 9
    assert body["strategy"]["stop_loss_pct"] == 6
    assert body["strategy"]["paper_first"] is True


def test_ai_parlay_chat_falls_back_to_best_candidate(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))

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
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))

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
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
    ]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))
    monkeypatch.setattr(web_app, "_openai_parlay_response", lambda message, suggestions, request=None: (None, "timeout"))

    body = ai_parlay_chat(ParlayChatPayload(message="give me a 3 leg parlay for WNBA", platform="PrizePicks", sport="All Sports"))

    assert body["ai_enabled"] is False
    assert body["ai_error"] == "timeout"
    assert body["request"]["sport"] == "WNBA"
    assert body["suggestion"]["leg_count"] == 3
    assert "best 3-leg parlay for WNBA" in body["message"]


def test_ai_parlay_chat_returns_structured_context(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "WNBA", "stat": "3-Pointers Made", "line": 2.5, "trending_count": 70000},
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))

    body = ai_parlay_chat(ParlayChatPayload(message="safer 3 leg WNBA", platform="PrizePicks", sport="All Sports"))

    assert body["request"]["risk_profile"] == "safe"
    assert body["search"]["relaxed"] is True
    assert body["search"]["exclude_correlated"] is False
    assert body["local_model"]["reasons"]
    assert "alternatives" in body


def test_ai_status_reports_key_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-an-openai-key")

    body = ai_status()

    assert body["configured"] is True
    assert body["key_format_ok"] is False


def test_ai_entry_review_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
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
    assert body["model"] == "edgeiq-local-v2.0"
    assert "Rules review" in body["review"]


def test_place_entry_saves_wager_and_multiplier(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        lambda entry, status="Draft", result="", wager=0.0, multiplier=1.0, recommended_by_app=False, audit_snapshot="", entry_mode="real", payout_type="standard": saved.setdefault(
            "payload",
            {"status": status, "wager": wager, "multiplier": multiplier, "recommended_by_app": recommended_by_app, "audit_snapshot": audit_snapshot, "entry_mode": entry_mode},
        ) or 11,
    )
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 90.0})
    monkeypatch.setattr(web_app, "_placement_check", lambda payload, platform_value=None: {
        "ok": True,
        "requires_confirmation": False,
        "warnings": [],
        "blocks": [],
        "props": [],
        "provider_rows": 0,
    })

    monkeypatch.setattr(web_app, "_entry_analysis", lambda entry, payload: {
        "release_verdict": {"paid_allowed": True},
        "risk_guardrails": [],
        "payout_analysis": {},
    })
    body = place_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "wager": 10,
                "multiplier": 3,
                "recommended_by_app": False,
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@OPP", "game_time": "2026-07-20T19:00:00Z"},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "game": "BBB@OPP", "game_time": "2026-07-20T20:00:00Z"},
                ],
            }
        )
    )

    assert body["status"] == "Pending"
    assert saved["payload"]["status"] == "Pending"
    assert saved["payload"]["wager"] == 10.0
    assert saved["payload"]["multiplier"] == 3.0
    assert saved["payload"]["recommended_by_app"] is False
    assert "recommendation" in saved["payload"]["audit_snapshot"]
    assert '"schema_version": 2' in saved["payload"]["audit_snapshot"]


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
    monkeypatch.setattr(web_app, "_entry_analysis", lambda entry, payload: {
        "release_verdict": {"paid_allowed": True},
        "risk_guardrails": [],
        "payout_analysis": {},
    })

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


def test_loss_protection_activates_on_negative_performance(monkeypatch):
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": "true" if key == "loss_protection_enabled" else default)
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "bankroll": 100.0,
        "profit": -12.0,
        "roi": -12.0,
        "monthly_profit": {"current_month": {"profit": -8.0, "roi": -8.0}},
        "entries": {"real": {"settled": 8}},
    })
    monkeypatch.setattr(web_app, "clv_report", lambda: {
        "entries": [],
        "average_clv": -0.4,
        "positive_clv_rate": 25.0,
        "tracked_legs": 8,
    })
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])

    body = web_app.loss_protection()

    assert body["active"] is True
    assert body["mode"] in {"watch", "lockdown"}
    assert any("negative" in reason.lower() or "roi" in reason.lower() for reason in body["reasons"])
    assert body["paid_rules"]


def test_loss_protection_toggle_disables_enforcement_without_hiding_trigger(monkeypatch):
    store = {"loss_protection_enabled": "true"}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "profit": -12.0,
        "roi": -12.0,
        "monthly_profit": {"current_month": {"profit": -8.0}},
        "entries": {},
    })
    monkeypatch.setattr(web_app, "clv_report", lambda: {"average_clv": -0.5, "positive_clv_rate": 20, "tracked_legs": 8})
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])

    body = web_app.update_loss_protection(web_app.LossProtectionSettingPayload(enabled=False))

    assert body["enabled"] is False
    assert body["triggered"] is True
    assert body["active"] is False
    assert body["mode"] == "off"
    assert store["loss_protection_enabled"] == "false"


def test_loss_protection_forces_lockdown_after_severe_drawdown(monkeypatch):
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": "false" if key == "loss_protection_enabled" else default)
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "profit": -60.0,
        "roi": -35.0,
        "monthly_profit": {"current_month": {"profit": -30.0}},
        "entries": {"real": {"wins": 2, "losses": 12}},
        "recommendation_accuracy": {"accuracy": 22.0, "decisions": 50},
    })
    monkeypatch.setattr(web_app, "clv_report", lambda: {"average_clv": -0.5, "positive_clv_rate": 20, "tracked_legs": 8})
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])

    body = web_app.loss_protection()

    assert body["enabled"] is False
    assert body["forced"] is True
    assert body["active"] is True
    assert body["mode"] == "lockdown"


def test_loss_protection_activates_on_weak_real_and_recommended_records(monkeypatch):
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": "true")
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {
        "profit": 3.0,
        "roi": 2.0,
        "monthly_profit": {"current_month": {"profit": 3.0}},
        "entries": {"wins": 3, "losses": 12},
        "recommendation_accuracy": {"accuracy": 23.6, "decisions": 89},
    })
    monkeypatch.setattr(web_app, "clv_report", lambda: {"average_clv": 0.2, "positive_clv_rate": 55, "tracked_legs": 8})
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])

    body = web_app.loss_protection()

    assert body["active"] is True
    assert body["metrics"]["real_win_rate"] == 20.0
    assert any("recommendations" in reason for reason in body["reasons"])


def test_place_real_entry_can_be_tracked_when_loss_protection_is_active(monkeypatch):
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": True})
    monkeypatch.setattr(web_app, "_end_to_end_placement_blocks", lambda payload: [])
    monkeypatch.setattr(web_app, "_generated_entry_day_blocks", lambda payload: [])
    monkeypatch.setattr(web_app, "_entry_analysis", lambda entry, payload: {
        "release_verdict": {"paid_allowed": True},
        "risk_guardrails": [],
        "payout_analysis": {},
        "loss_protection": {"active": True},
    })
    monkeypatch.setattr(web_app.EntryRepository, "save", lambda *args, **kwargs: 91)
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "wager": 10,
        "entry_mode": "real",
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@BBB", "game_time": _today_game_time()},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
        ],
    })

    body = place_entry(payload)

    assert body["id"] == 91
    assert body["loss_protection_active"] is True
    assert body["entry_mode"] == "real"


def test_paid_tracking_override_records_entry_without_model_endorsement(monkeypatch):
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": True})
    monkeypatch.setattr(web_app, "_end_to_end_placement_blocks", lambda payload: [])
    monkeypatch.setattr(web_app, "_generated_entry_day_blocks", lambda payload: [])
    monkeypatch.setattr(web_app, "_entry_analysis", lambda entry, payload: {
        "release_verdict": {"paid_allowed": False, "reasons": ["Negative expected value."]},
        "risk_guardrails": [{"severity": "danger", "message": "Loss Protection is active."}],
        "payout_analysis": {},
        "loss_protection": {"active": True},
    })
    monkeypatch.setattr(web_app.EntryRepository, "save", lambda *args, **kwargs: 92)
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "wager": 10,
        "tracking_override": True,
        "entry_mode": "real",
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
        ],
    })

    body = place_entry(payload)

    assert body["id"] == 92
    assert body["tracking_override"] is True


def test_placement_check_includes_loss_protection_audit(monkeypatch):
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@BBB", "game_time": "2026-07-16T23:00:00Z", "platform": platform},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "game": "AAA@BBB", "game_time": "2026-07-16T23:00:00Z", "platform": platform},
    ])
    monkeypatch.setattr(web_app, "_platform_value_check", lambda payload: {
        "recommended_platform": "PrizePicks",
        "recommendation": "PrizePicks has the current best value.",
    })
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {
        "active": True,
        "mode": "watch",
        "score": 61,
        "label": "Loss Protection Active",
        "reasons": ["Current month is negative at $-8.00."],
        "metrics": {},
        "paid_rules": ["Loss Protection: paid entries are limited to 1-2 legs."],
    })
    monkeypatch.setattr(web_app, "_loss_protection_entry_flags", lambda entry, payload: [{
        "severity": "warning",
        "message": "Recent CLV is negative; line-shop before placing or keep this as paper.",
    }])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 100.0})

    body = placement_check(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "game_time": _today_game_time(),
                "wager": 5,
                "props": [
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
                ],
            }
        )
    )

    labels = [item["label"] for item in body["audit"]["items"]]
    assert "Loss protection" in labels
    assert body["loss_protection"]["active"] is True
    assert any("CLV" in warning for warning in body["warnings"])
    assert body["tracking_override_allowed"] is True
    assert body["tracking_blocks"] == []


def test_place_paper_entry_does_not_require_wager(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        lambda entry, status="Draft", result="", wager=0.0, multiplier=1.0, recommended_by_app=False, audit_snapshot="", entry_mode="real", payout_type="standard": saved.setdefault(
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
                    {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@OPP", "game_time": "2026-07-20T19:00:00Z"},
                    {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5, "game": "BBB@OPP", "game_time": "2026-07-20T20:00:00Z"},
                ],
            }
        )
    )

    assert body["entry_mode"] == "paper"
    assert saved["payload"]["entry_mode"] == "paper"
    assert saved["payload"]["wager"] == 0
    assert '"entry_mode": "paper"' in saved["payload"]["audit_snapshot"]
    assert "dashboard" not in body


def test_place_manual_underdog_entry_blocks_missing_settlement_context(monkeypatch):
    saved = {}
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": False})
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(web_app, "get_dashboard", lambda: {"bankroll": 100.0, "monthly_profit": 0.0})
    monkeypatch.setattr(
        web_app.EntryRepository,
        "save",
        lambda entry, **kwargs: saved.setdefault("entry", entry) and 31,
    )

    with pytest.raises(web_app.HTTPException) as exc:
        place_entry(EntryPayload.model_validate({
            "platform": "Underdog",
            "entry_mode": "real",
            "wager": 5,
            "multiplier": 6,
            "recommended_by_app": False,
            "props": [
                {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
                {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
            ],
        }))
    assert "complete current provider match" in exc.value.detail


def test_place_recommended_real_entry_still_requires_verified_settlement(monkeypatch):
    monkeypatch.setattr(web_app, "_loss_protection_payload", lambda: {"active": False})
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: [])
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "entry_mode": "real",
        "wager": 5,
        "recommended_by_app": True,
        "props": [
            {
                "player": "A",
                "team": "AAA",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "game": "AAA@BBB",
                "game_time": _today_game_time(),
            },
        ],
    })

    with pytest.raises(web_app.HTTPException) as exc_info:
        place_entry(payload)

    assert exc_info.value.status_code == 400
    assert "cannot be tracked automatically" in exc_info.value.detail


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
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: _verified_rows(raw_props))

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
    assert '"schema_version": 2' in saved["payload"]["audit_snapshot"]


def test_auto_paper_calibration_dry_run_does_not_save(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000, "platform": "PrizePicks"},
    ]
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: _verified_rows(raw_props))
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
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: _verified_rows(raw_props) if sport in (None, "WNBA") else [])
    monkeypatch.setattr(
        web_app,
        "_confirmed_props_payload",
        lambda platform, sport, limit=120: {"raw_props": _verified_rows(raw_props) if sport == "WNBA" else [], "count": len(raw_props), "sport": sport or "WNBA"},
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


def test_auto_paper_targets_weak_confidence_buckets_before_other_segments():
    targets = web_app._calibration_learning_targets({
        "calibration": [
            {"label": "40-50%", "bets": 40, "error": -5.0},
            {"label": "80-90%", "bets": 4, "error": -38.0},
        ],
        "what_fails": [
            {"type": "Stat", "name": "Assists", "tracked": 3, "win_rate": 25, "roi": -40},
        ],
    }, "WNBA")

    assert targets[0]["type"] == "Confidence"
    assert targets[0]["name"] == "80-90%"
    assert targets[0]["confidence_low"] == 80
    assert targets[0]["calibration_error"] == 38.0
    assert targets[-1]["type"] == "Coverage"


def test_auto_paper_confidence_target_filters_actual_candidate_bucket(monkeypatch):
    captured = {}
    rows = _verified_rows([
        {"player": "Low", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5},
        {"player": "Target A", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5},
        {"player": "Target B", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5},
    ])
    confidence_by_player = {"Low": 42.0, "Target A": 84.0, "Target B": 89.9}

    monkeypatch.setattr(web_app, "_analyzed_feed_prop", lambda prop: {
        **prop,
        "confidence": confidence_by_player[prop["player"]],
        "projection": float(prop["line"]) + 1,
        "direction": "Over",
    })
    monkeypatch.setattr(web_app, "suggest_entries", lambda raw_props, *args, **kwargs: captured.setdefault("props", raw_props) or [])

    web_app._paper_calibration_suggestions_for_props(
        AutoPaperCalibrationPayload(sport="WNBA"),
        {"type": "Confidence", "confidence_low": 80, "confidence_high": 90},
        rows,
        "WNBA",
    )

    assert {prop["player"] for prop in captured["props"]} == {"Target A", "Target B"}


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


def test_entry_analysis_suggests_direction_changes_and_removals(monkeypatch):
    monkeypatch.setattr(web_app.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "_end_to_end_prop_eligibility", lambda *args, **kwargs: {"eligible": True, "reasons": []})
    monkeypatch.setattr(web_app, "_prop_data_quality", lambda prop: {"score": 72.0, "label": "partial data", "flags": []})

    body = analyze_entry(
        EntryPayload.model_validate(
            {
                "platform": "PrizePicks",
                "props": [
                    {
                        "player": "Wrong Side",
                        "team": "AAA",
                        "sport": "WNBA",
                        "stat": "Points",
                        "line": 20.5,
                        "projection": 18.0,
                        "direction": "Over",
                    },
                    {
                        "player": "Thin Edge",
                        "team": "BBB",
                        "sport": "WNBA",
                        "stat": "Assists",
                        "line": 7.5,
                        "projection": 7.7,
                        "direction": "Over",
                    },
                ],
            }
        )
    )

    corrections = body["corrections"]
    assert corrections["manual_entry"] is True
    assert corrections["change_count"] == 2
    assert corrections["legs"][0]["action"] == "flip"
    assert corrections["legs"][0]["suggested_direction"] == "Under"
    assert corrections["legs"][0]["message"] == "EdgeIQ suggests Under on this prop."
    assert corrections["legs"][1]["action"] == "remove"
    assert corrections["legs"][1]["message"] == "EdgeIQ suggests removing this prop."


def test_standard_calibration_batch_uses_fixed_leg_plan_and_distinct_targets(monkeypatch):
    targets = [
        {"type": "Confidence", "name": "40-50%", "sport": "WNBA"},
        {"type": "Confidence", "name": "50-60%", "sport": "WNBA"},
        {"type": "Confidence", "name": "60-70%", "sport": "WNBA"},
        {"type": "Confidence", "name": "70-80%", "sport": "WNBA"},
        {"type": "Confidence", "name": "80-90%", "sport": "WNBA"},
    ]
    observed: list[tuple[int, str]] = []
    created: list[dict] = []
    monkeypatch.setattr(web_app, "_paper_calibration_suggestions", lambda *args, **kwargs: [object()])

    def fake_append(suggestion, target, payload, backtest_data, signatures, rows, skipped):
        observed.append((payload.leg_count, target["name"]))
        rows.append({"suggestion": {"leg_count": payload.leg_count}})
        return True

    monkeypatch.setattr(web_app, "_append_calibration_entry", fake_append)
    web_app._create_standard_calibration_batch(
        AutoPaperCalibrationPayload(sport="WNBA", standard_batch=True),
        targets,
        {},
        set(),
        created,
        [],
        {},
        {},
    )

    assert [leg_count for leg_count, _target in observed] == [2, 2, 3, 4, 5]
    assert len({target for _leg_count, target in observed}) == 5
    assert [row["suggestion"]["leg_count"] for row in created] == [2, 2, 3, 4, 5]


def test_automatic_paper_samples_uses_saved_defaults(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        web_app,
        "_user_preferences",
        lambda: {"default_platform": "Underdog", "default_sport": "NFL"},
    )

    def fake_auto_paper(payload):
        captured["payload"] = payload
        return {"created_count": 2}

    monkeypatch.setattr(web_app, "_auto_paper_calibration", fake_auto_paper)

    result = web_app._run_automatic_paper_samples()

    assert captured["payload"].platform == "Underdog"
    assert captured["payload"].sport == "NFL"
    assert captured["payload"].standard_batch is True
    assert captured["payload"].max_entries == 5
    assert result["automatic"] is True
    assert "Created 2" in result["message"]


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
    assert EntryRepository._default_multiplier_for_legs(3) == 6.0
    assert EntryRepository._default_multiplier_for_legs(8, "Underdog") == 120.0
    assert EntryRepository._default_multiplier_for_legs(99) == 3.0


def test_underdog_eight_leg_dnp_reduces_to_seven_leg_multiplier():
    result, profit = EntryRepository._settlement_profit(
        result="Win",
        wager=10,
        multiplier=120,
        leg_count=8,
        dnp_legs=1,
        dnp_mode="reduce",
        platform="Underdog",
    )

    assert result == "Win"
    assert profit == 640.0


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


def test_entry_suggestions_generate_exact_requested_leg_count(monkeypatch):
    raw_props = [
        {
            "player": f"P{i}",
            "team": f"T{i}",
            "league": "WNBA",
            "stat": "Points",
            "line": 10.5 + i,
            "trending_count": 100000 - i,
            "platform": "PrizePicks",
            "game_time": _today_game_time(),
        }
        for i in range(8)
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)

    body = entry_suggestions(sport="WNBA", platform="PrizePicks")

    assert body["mode"] == "prizepicks_2_leg"
    assert len(body["suggestions"]) == 5
    assert [suggestion["rank"] for suggestion in body["suggestions"]] == [1, 2, 3, 4, 5]
    assert [suggestion["leg_count"] for suggestion in body["suggestions"]] == [2, 2, 2, 2, 2]


def test_confirmed_props_require_game_time_and_clean_market(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "game": "AAA@OPP", "game_time": _today_game_time(), "trending_count": 100000, "platform": "PrizePicks"},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Points", "line": 18.5, "game_time": "", "trending_count": 90000, "platform": "PrizePicks"},
        {"player": "C", "team": "CCC", "league": "NFL", "stat": "Season Pass Yards", "line": 4000.5, "game_time": "2026-09-01T13:00:00-04:00", "trending_count": 80000, "platform": "Underdog", "season_type": "season_long"},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [prop for prop in raw_props if sport is None or prop["league"] == sport])
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = confirmed_props(platform="PrizePicks", sport="WNBA", limit=10)

    assert body["count"] == 1
    assert body["props"][0]["player"] == "A"
    assert body["props"][0]["confirmation"]["game_time_confirmed"] is True


def test_confirmed_props_bounds_expensive_analysis_for_large_feeds(monkeypatch):
    raw_props = [
        {"player": f"P{i}", "league": "WNBA", "stat": "Points", "line": 10.5, "game_time": _today_game_time(), "trending_count": i}
        for i in range(1000)
    ]
    analyzed_calls = []
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app, "_end_to_end_prop_eligibility", lambda raw: {"eligible": True, "provider": "espn"})

    def analyzed(raw):
        analyzed_calls.append(raw["player"])
        return {**raw, "sport": "WNBA", "platform": "PrizePicks", "confidence": 55, "edge": 1, "confirmed_score": 55}

    monkeypatch.setattr(web_app, "_analyzed_feed_prop", analyzed)
    monkeypatch.setattr(web_app, "_confirmed_prop_candidate", lambda raw, row: {**row, "_raw": raw})

    body = web_app._confirmed_props_payload("PrizePicks", "WNBA", limit=20)

    assert len(analyzed_calls) == 120
    assert body["analyzed_count"] == 1000
    assert body["count"] == 120


def test_confirmed_entry_suggestions_use_confirmed_pool(monkeypatch):
    raw_props = [
        {
            "player": f"P{i}",
            "team": f"T{i}",
            "league": "WNBA",
            "stat": "Points",
                "line": 10.5 + i,
                "game": f"T{i}@OPP",
                "game_time": _today_game_time(),
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


def test_crazy_six_uses_current_end_to_end_verified_unique_legs(monkeypatch):
    raw_props = _verified_rows([
        {
            "player": f"P{i}",
            "team": f"T{i}",
            "league": "WNBA",
            "stat": ("Points", "Assists", "Rebounds")[i % 3],
            "line": 10.5 + i,
            "trending_count": 100000 - i,
            "platform": "PrizePicks",
        }
        for i in range(8)
    ])
    monkeypatch.setattr(web_app, "_fetch_platform_props", lambda platform: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "_card_release_status", lambda card: {"ok": False, "blocks": ["High variance"], "warnings": []})

    body = web_app.crazy_six_suggestion(sport="All Sports", platform="PrizePicks")

    assert body["suggestion"]["leg_count"] == 6
    assert body["suggestion"]["risk_tier"] == "Crazy 6-Leg"
    assert body["verification"]["end_to_end_verified"] is True
    assert body["verification"]["current_provider_lines"] is True
    assert body["verification"]["confirmed_game_times"] is True
    assert body["verification"]["unique_players"] is True
    assert body["sports_used"] == ["WNBA"]


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
    assert body["provider_count"] == 2
    assert body["market_count"] == 2
    assert body["no_vig"]["hold"] > 0
    assert body["no_vig_source"] == "Manual odds"


def test_line_shop_uses_live_exact_line_no_vig_when_manual_odds_are_absent(monkeypatch):
    raw_props = [{
        "player": "A",
        "team": "IND",
        "league": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "trending_count": 1000,
        "platform": "PrizePicks",
        "game": "SEA",
    }]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app.sportsbook_odds,
        "get_player_prop_consensus",
        lambda *args, **kwargs: {
            "available": True,
            "over_probability": 53.0,
            "under_probability": 47.0,
            "average_hold": 4.2,
            "book_count": 4,
            "last_update": "2026-07-29T18:00:00Z",
            "stale": False,
        },
    )

    body = line_shop("A", "Points", sport="WNBA", platform="PrizePicks")

    assert body["no_vig_source"] == "The Odds API"
    assert body["no_vig"]["over_probability"] == 53.0
    assert body["no_vig"]["book_count"] == 4


def test_line_shop_excludes_adjusted_lines_from_standard_comparison(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 17, "trending_count": 1000, "platform": "PrizePicks", "line_offer_type": "standard"},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 9.5, "trending_count": 900, "platform": "PrizePicks", "line_offer_type": "goblin", "adjusted_line": True, "is_discounted_line": True},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 26.5, "trending_count": 800, "platform": "PrizePicks", "line_offer_type": "demon", "adjusted_line": True, "is_premium_line": True},
    ]
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: raw_props)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = line_shop("A", "Points", sport="WNBA", platform="PrizePicks")

    assert body["provider_count"] == 1
    assert body["market_count"] == 3
    assert body["adjusted_market_count"] == 2
    assert body["best_over"]["line"] == 17
    assert body["best_under"]["line"] == 17
    assert body["line_spread"] == 0


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
    assert "last_20" in body["splits"]
    assert "trend" in body
    assert body["market_lines"][0]["platform"] == "PrizePicks"
    assert body["active_props"][0]["platform"] == "PrizePicks"
    assert body["recommendation"]["player"] == "A"
    assert body["forecast"]["distribution"]["median"] is not None
    assert len(body["projection_sensitivity"]["scenarios"]) == 3
    assert "starter" in body["splits"]
    assert "bench" in body["splits"]
    assert "closing_lines" in body


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
    assert body["delivery_hooks"]["email"] == "needs SMTP credentials"


def test_alert_delivery_posts_configured_webhook(monkeypatch):
    store = {
        "alert_delivery_settings": json.dumps({
            "browser_enabled": False,
            "email_enabled": False,
            "sms_enabled": False,
            "webhook_enabled": True,
            "webhook_url": "https://example.test/hook",
            "min_priority": 50,
        })
    }
    posted = {}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))

    class Response:
        status_code = 204

    def fake_post(url, json=None, timeout=0):
        posted["url"] = url
        posted["json"] = json
        posted["timeout"] = timeout
        return Response()

    monkeypatch.setattr(web_app.requests, "post", fake_post)

    body = send_test_alert_delivery(AlertDeliveryTestPayload(priority=75))

    assert body["delivered"] is True
    assert body["channels"][0]["status"] == "sent"
    assert posted["url"] == "https://example.test/hook"


def test_deploy_readiness_reports_local_app_as_ready(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("EDGEIQ_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("EDGEIQ_DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("EDGEIQ_ALERT_WEBHOOK_URL", raising=False)

    body = deploy_readiness()

    labels = {check["label"]: check for check in body["checks"]}
    assert body["mode"] == "local"
    assert body["status"] == "local ready"
    assert body["score"] == 100
    assert labels["PWA manifest"]["ok"] is True
    assert labels["Service worker"]["ok"] is True
    assert labels["App database"]["ok"] is True
    assert labels["App database"]["status"] == "local ready"
    assert labels["Allowed origins"]["required"] is False
    assert labels["Alert webhook"]["status"] == "optional"


def test_deploy_readiness_requires_hosted_database_in_hosted_mode(monkeypatch):
    monkeypatch.setenv("EDGEIQ_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///edgeiq.db")
    monkeypatch.delenv("EDGEIQ_ALLOWED_ORIGINS", raising=False)

    body = deploy_readiness()

    labels = {check["label"]: check for check in body["checks"]}
    assert body["mode"] == "hosted"
    assert body["status"] == "hosted needs setup"
    assert labels["Production database"]["required"] is True
    assert labels["Production database"]["ok"] is False
    assert labels["Allowed origins"]["required"] is True


def test_share_entry_persists_copy_ready_slip(monkeypatch):
    store = {}
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])

    payload = ShareSlipPayload.model_validate({
        "platform": "PrizePicks",
        "wager": 10,
        "multiplier": 3,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Assists", "line": 7.5},
        ],
        "note": "test slip",
    })

    body = share_entry(payload)
    shared = shared_entry(body["id"])

    assert body["share_url"].startswith("/share/")
    assert shared["note"] == "test slip"
    assert "EdgeIQ 2-leg handoff" in shared["copy_text"]


def test_grading_report_summarizes_unknowns_and_clv(monkeypatch):
    entries = [{
        "id": 1,
        "status": "Settled",
        "result": "Win",
        "platform": "PrizePicks",
        "wager": 10,
        "multiplier": 3,
        "profit": 20,
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "line": 20.5, "platform": "PrizePicks", "final_result": "Win", "actual": 24, "final_source": "espn"},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "line": 7.5, "platform": "PrizePicks", "final_result": "", "actual": None, "final_source": ""},
        ],
    }]
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [])
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)
    monkeypatch.setattr(web_app, "_active_line_for_player_stat", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", lambda *args, **kwargs: [])

    body = grading_report()

    assert body["summary"]["unknown_legs"] == 1
    assert body["summary"]["verified_legs"] == 1
    assert body["summary"]["verification_rate"] == 50.0


def test_compact_grading_report_omits_heavy_detail(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: [{"id": 9}])
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(
        web_app,
        "_entry_progress_payload",
        lambda entry, include_market_detail=False: {
            "id": entry["id"],
            "tracker_status": "waiting",
            "next_game_time_label": "Tonight",
            "time_groups": [{"large": "payload"}],
            "legs": [{"player": "A", "status": "scheduled", "timeline_label": "Starts tonight", "large": "payload"}],
        },
    )
    monkeypatch.setattr(web_app, "clv_report", lambda: {
        "entries": [{"id": 1, "legs": [{"player": "A"}]}],
        "average_clv": 1.5,
        "positive_clv_rate": 60.0,
        "tracked_legs": 5,
        "quarantined_legs": 1,
    })

    body = grading_report(compact=True)

    assert body["summary"]["average_clv"] == 1.5
    assert "completed" not in body
    assert "clv" not in body
    assert body["pending"] == [{
        "id": 9,
        "status": "waiting",
        "timeline_label": "Tonight",
        "legs": [{"player": "A", "status": "scheduled", "timeline_label": "Starts tonight"}],
    }]


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
    monkeypatch.setattr(
        web_app.sportsbook_odds,
        "get_player_prop_consensus",
        lambda player, stat, sport, game, line, direction, team="": {
            "available": True,
            "market_probability": 54.0,
            "book_count": 3,
            "dfs_offers": [
                {"platform": "PrizePicks", "line": line, "over": {"multiplier": 1.0}, "under": {"multiplier": 1.0}},
                {"platform": "Underdog", "line": line, "over": {"multiplier": 1.1}, "under": {"multiplier": 1.0}},
            ],
            "reason": "Exact-line market found.",
        },
    )

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
    assert "No matched provider clears positive expected value" in body["recommendation"]
    assert body["legs"][0]["best_line"] == 19.5
    assert body["legs"][0]["market_consensus"]["market_probability"] == 54.0
    assert all(row["payout_evidence"]["live_offer_legs"] == 2 for row in body["platforms"])


def test_sportsbook_integrations_reports_manual_handoff(monkeypatch):
    monkeypatch.delenv("EDGEIQ_BET_HISTORY_FILE", raising=False)
    monkeypatch.delenv("EDGEIQ_FINAL_STATS_FILE", raising=False)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    body = web_app.sportsbook_integrations()

    assert body["connected"] is False
    assert body["market_data_connected"] is False
    assert body["import_ready"] is False
    assert any(connector["name"] == "PrizePicks" for connector in body["connectors"])
    assert any(connector["name"] == "The Odds API" for connector in body["connectors"])
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

    assert body["count"] == 0


def test_prizepicks_adjusted_lines_use_standard_baseline(monkeypatch):
    captured_history_scope = {}

    def scoped_history(*args, **kwargs):
        captured_history_scope.update(kwargs)
        return []

    raw_props = [
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100, "platform": "PrizePicks", "odds_type": "standard", "game": "AAA@BBB"},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 18.5, "trending_count": 90, "platform": "PrizePicks", "odds_type": "goblin", "adjusted_odds": True, "game": "AAA@BBB"},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 24.5, "trending_count": 80, "platform": "PrizePicks", "odds_type": "demon", "adjusted_odds": True, "game": "AAA@BBB"},
    ]
    monkeypatch.setattr(web_app.LineHistoryRepository, "get_history", scoped_history)

    enriched = web_app._enrich_prizepicks_adjusted_lines(raw_props)
    discounted = next(prop for prop in enriched if prop["line_offer_type"] == "goblin")
    analyzed = web_app._analyzed_feed_prop(discounted)

    assert discounted["standard_line"] == 20.5
    assert analyzed["baseline_line"] == 20.5
    assert analyzed["line"] == 18.5
    assert analyzed["is_discounted_line"] is True
    assert analyzed["edge"] == 2
    assert any(label["label"] == "Discounted line" for label in analyzed["data_strength"])
    assert captured_history_scope == {"game": "AAA@BBB", "line_offer_type": "goblin"}


def test_prizepicks_adjusted_lines_infer_premium_side_from_standard_line() -> None:
    rows = web_app._enrich_prizepicks_adjusted_lines([
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 18.5, "platform": "PrizePicks"},
        {"player_id": "1", "player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 39.5, "platform": "PrizePicks", "adjusted_odds": True},
    ])

    premium = next(row for row in rows if row["line"] == 39.5)

    assert premium["standard_line"] == 18.5
    assert premium["line_offer_type"] == "demon"
    assert premium["is_premium_line"] is True


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
        lambda player, stat, platform, **kwargs: [
            {"line": 20.5, "recorded_at": datetime(2026, 7, 10, 10, 0)}
        ] if player == "A" else [],
    )

    body = market_timing_alerts(platform="PrizePicks", sport="WNBA", limit=5)

    assert body["count"] >= 1
    assert body["alerts"][0]["type"] == "Line Moved Against Price"
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
                    {
                        "player": "A",
                        "sport": "WNBA",
                        "stat": "Points",
                        "line": 20.5,
                        "platform": "PrizePicks",
                        "game": "AAA@BBB",
                        "game_time": "2026-07-08T19:00:00Z",
                        "line_offer_type": "standard",
                        "projection_source": "provider_projection",
                        "direction": "Over",
                    }
                ],
            }
        ],
    )
    bulk_calls = []

    def bulk_histories(requests):
        bulk_calls.append(requests)
        return {
            web_app._clv_history_key(requests[0]): [
                {"line": 22.5, "recorded_at": datetime(2026, 7, 8, 18, 55)}
            ]
        }

    monkeypatch.setattr(web_app.LineHistoryRepository, "get_histories", bulk_histories)

    body = clv_report()

    assert body["tracked_legs"] == 1
    assert body["average_clv"] == 2.0
    assert body["entries"][0]["legs"][0]["beat_market"] is True
    assert len(bulk_calls) == 1


def test_clv_report_quarantines_legacy_lines_without_offer_provenance(monkeypatch):
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [{
        "id": 1,
        "status": "Settled",
        "placed_at": datetime(2026, 7, 8, 12, 0),
        "props": [{
            "player": "A",
            "sport": "WNBA",
            "stat": "Points",
            "line": 38.5,
            "platform": "PrizePicks",
            "game": "AAA@BBB",
            "game_time": "2026-07-08T19:00:00Z",
        }],
    }])

    body = clv_report()

    assert body["tracked_legs"] == 0
    assert body["quarantined_legs"] == 1
    assert body["entries"][0]["legs"][0]["reliability_reason"] == "legacy_offer_metadata_missing"


def test_clv_report_bulk_loads_histories_once(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [{
        "id": 1,
        "status": "Settled",
        "result": "Win",
        "platform": "PrizePicks",
        "placed_at": datetime(2026, 8, 7, tzinfo=UTC),
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "platform": "PrizePicks", "line": 10, "game": "AAA@BBB", "game_time": "2026-08-07T23:00:00Z", "projection_source": "provider"},
            {"player": "B", "sport": "WNBA", "stat": "Assists", "platform": "PrizePicks", "line": 5, "game": "AAA@BBB", "game_time": "2026-08-07T23:00:00Z", "projection_source": "provider"},
        ],
    }])
    monkeypatch.setattr(
        web_app.LineHistoryRepository,
        "get_histories",
        lambda requests: calls.append(requests) or {},
    )
    monkeypatch.setattr(
        web_app.LineHistoryRepository,
        "get_history",
        lambda *args, **kwargs: pytest.fail("per-leg history query should not run"),
    )

    body = web_app._clv_report_payload()

    assert len(calls) == 1
    assert len(calls[0]) == 2
    assert body["quarantined_legs"] == 2


def test_static_ui_exposes_paid_or_paper_choice_and_named_controls():
    root = Path(web_app.__file__).parent / "static"
    app_source = (root / "app.js").read_text(encoding="utf-8")
    shell_source = (root / "ui-shell.js").read_text(encoding="utf-8")
    html_source = (root / "index.html").read_text(encoding="utf-8")
    service_worker_source = (root / "sw.js").read_text(encoding="utf-8")

    assert "chooseEntrySaveMode" in app_source
    assert "directionalEdge" in app_source
    assert "Switch to Paper" in shell_source
    assert 'role="dialog"' in shell_source
    assert 'aria-label="Starting bankroll"' in shell_source
    assert 'aria-label="Optimizer platform"' in html_source
    assert 'aria-label="Import type"' in html_source
    assert 'aria-label="Projection assist sport"' in html_source
    assert 'updateViaCache: "none"' in app_source
    assert 'cache: "no-store"' in service_worker_source


def test_index_disables_stale_html_caching():
    response = web_app.index()

    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


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
    assert body["summary"]["saved_bets"] == 0
    assert body["summary"]["completed_entries"] == 1


def test_bets_endpoint_does_not_return_synced_entry_mirrors(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(
        web_app.BetRepository,
        "get_all",
        lambda self, include_synced_entries=False: calls.append(include_synced_entries) or [],
    )

    body = bets()

    assert body["bets"] == []
    assert calls == [False]


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
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))

    body = optimize_entries(platform="PrizePicks", sport="MLB", min_legs=2, max_legs=3, limit=3)

    assert [suggestion["rank"] for suggestion in body["suggestions"]] == [1, 2, 3]
    assert {suggestion["leg_count"] for suggestion in body["suggestions"]} <= {2, 3}
    assert "paid_ready_count" in body
    assert "best_value_pick" in body
    assert "obstacles" in body
    assert all("platform_value" in suggestion for suggestion in body["suggestions"])
    assert all("value_adjusted_score" in suggestion for suggestion in body["suggestions"])
    assert all("portfolio" in suggestion for suggestion in body["suggestions"])
    assert "portfolio_ready_count" in body


def test_web_optimizer_applies_filters(monkeypatch):
    raw_props = [
        {"player": "A", "team": "AAA", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 100000},
        {"player": "B", "team": "AAA", "league": "MLB", "stat": "Runs", "line": 0.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "MLB", "stat": "RBIs", "line": 0.5, "trending_count": 80000},
    ]
    monkeypatch.setattr(web_app.prizepicks, "fetch_projections", lambda limit=1000: _verified_rows(raw_props))

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


def test_settlement_uses_eastern_slate_date_for_late_live_entry():
    entry = {"placed_at": datetime(2026, 8, 7, 2, 0)}

    assert web_app._entry_placed_date(entry).isoformat() == "2026-08-06"


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


def test_auto_check_keeps_entry_pending_when_one_leg_loses_and_others_are_unknown(monkeypatch):
    settled = {}
    partial = {}
    final_stats_by_player = {
        "A": {"actual": 17.0, "status": "played", "source": "test"},
        "B": None,
    }
    monkeypatch.setattr(web_app, "_final_stat_for_prop", lambda prop: final_stats_by_player[prop["player"]])
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
    monkeypatch.setattr(
        web_app.EntryRepository,
        "store_partial_leg_results",
        lambda entry_id, legs: partial.update({"entry_id": entry_id, "legs": legs}),
    )
    entry = {
        "id": 42,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 22.0},
            {"player": "B", "team": "BBB", "sport": "WNBA", "stat": "Points", "line": 15.5, "projection": 16.0},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is False
    assert body["result"] == "Unknown"
    assert "every leg" in body["message"]
    assert settled == {}
    assert partial["entry_id"] == 42
    assert partial["legs"][0]["result"] == "Loss"
    assert partial["legs"][1]["result"] == "Unknown"


def test_auto_check_does_not_settle_from_live_stats(monkeypatch):
    settled = {}
    monkeypatch.setattr(
        web_app,
        "_final_stat_for_prop",
        lambda prop: {"actual": 17.0, "status": "live", "source": "espn_live"},
    )
    monkeypatch.setattr(web_app.EntryRepository, "settle", lambda entry_id, result, **kwargs: settled.update({entry_id: result}))
    entry = {
        "id": 44,
        "props": [
            {"player": "A", "team": "AAA", "sport": "WNBA", "stat": "Points", "line": 20.5, "projection": 22.0},
        ],
    }

    body = _check_entry_result(entry, allow_estimates=False)

    assert body["settled"] is False
    assert body["legs"][0]["actual"] is None
    assert settled == {}


def test_recent_partial_loss_is_reopened_before_final_stat_check(monkeypatch):
    reopened = []
    monkeypatch.setattr(
        web_app.EntryRepository,
        "all",
        lambda: [{
            "id": 99,
            "status": "Settled",
            "result": "Loss",
            "settled_at": web_app.utc_now(),
            "props": [
                {
                    "player": "A",
                    "game_time": web_app.iso_utc(web_app.utc_now()),
                    "actual": 17.0,
                    "final_result": "Loss",
                    "final_status": "played",
                },
                {
                    "player": "B",
                    "game_time": web_app.iso_utc(web_app.utc_now()),
                    "actual": None,
                    "final_result": "Unknown",
                    "final_status": "unknown",
                },
            ],
        }],
    )
    monkeypatch.setattr(
        web_app.EntryRepository,
        "reopen_for_settlement",
        lambda entry_id, reason: reopened.append((entry_id, reason)),
    )

    ids = web_app._reopen_recent_partial_settlements()

    assert ids == [99]
    assert reopened[0][0] == 99
    assert "before every leg" in reopened[0][1]


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
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": default)

    body = entry_progress()

    assert body == {
        "entries": [],
        "active": 0,
        "with_live_stats": 0,
        "settlement_sla": {
            "status": "clear",
            "overdue_legs": 0,
            "overdue_entries": 0,
            "legs": [],
            "message": "No pending legs are beyond the final-stat SLA.",
        },
        "auto_check": None,
        "game_time_sync": {"provider": "espn", "skipped": True, "updated": 0, "fetched_rows": 0, "errors": []},
        "live_stats_sync": {"provider": "espn_live", "skipped": True, "imported": 0, "fetched_rows": 0, "errors": []},
        "settlement_refresh": {},
    }


def test_settlement_sla_escalates_overdue_final_stats():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    row = web_app._leg_settlement_sla(
        {"sport": "WNBA", "game_time": "2026-07-29T04:00:00Z"},
        None,
        now,
    )

    assert row["overdue"] is True
    assert row["status"] == "overdue"
    assert "Recheck Final Stats" in row["message"]


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

    body = entry_progress(refresh_providers=True)

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

    body = entry_progress(auto_check=True, refresh_providers=True)

    assert calls == {"allow_estimates": False, "refresh_providers": True}
    assert body["auto_check"]["settled"] == 1


def test_entry_progress_refreshes_live_stats_when_explicitly_requested(monkeypatch):
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

    body = entry_progress(refresh_providers=True)

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


def test_final_stats_match_mlb_arizona_abbreviation_alias():
    rows = [SimpleNamespace(game="SD@ARI", game_date="2026-08-04", id=1)]

    assert _best_matching_row(rows, "SD @ AZ").game == "SD@ARI"


def test_end_to_end_eligibility_accepts_legacy_team_and_opponent_context():
    result = web_app._end_to_end_prop_eligibility({
        "player": "Shakira Austin",
        "team": "WAS",
        "league": "WNBA",
        "stat": "Points",
        "game": "DAL",
        "game_time": "2026-08-05T19:30:00-04:00",
    })

    assert result["eligible"] is True


def test_final_stats_match_expansion_team_aliases():
    rows = [
        SimpleNamespace(game="POR@MIN", game_date="2026-07-18", id=1),
        SimpleNamespace(game="WSH@GS", game_date="2026-07-18", id=2),
    ]

    assert _best_matching_row(rows[:1], "PDX", "MIN").game == "POR@MIN"
    assert _best_matching_row(rows[1:], "GSV", "WAS").game == "WSH@GS"


def test_final_stats_prefer_final_row_over_stale_live_row():
    rows = [
        SimpleNamespace(game="NY@IND", game_date="2026-07-18", id=12, status="live"),
        SimpleNamespace(game="NY@IND", game_date="2026-07-18", id=8, status="played"),
    ]

    assert _best_matching_row(rows, "IND", "NYL").status == "played"


def test_espn_basketball_summary_extracts_made_threes():
    rows = espn._basketball_stat_rows(
        "Sabrina Ionescu",
        "NY",
        "WNBA",
        "NY@IND",
        datetime(2026, 7, 18).date(),
        {"PTS": 12, "REB": 1, "AST": 4, "3PT": "2-7"},
    )

    threes = next(row for row in rows if row["stat"] == "3-Pointers Made")
    assert threes["actual"] == 2
    assert espn._stats_by_label(["3PT"], ["3-8"])["3PT"] == 3


def test_espn_baseball_summary_calculates_prizepicks_pitcher_points_and_hits():
    summary = {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": "DET"}},
            {"homeAway": "home", "team": {"abbreviation": "LAA"}},
        ]}]},
        "boxscore": {"players": [{
            "team": {"abbreviation": "DET"},
            "statistics": [
                {
                    "labels": ["H-AB", "AB", "R", "H", "RBI", "HR"],
                    "athletes": [{"athlete": {"displayName": "Test Hitter"}, "stats": ["2-4", "4", "1", "2", "1", "0"]}],
                },
                {
                    "labels": ["IP", "H", "R", "ER", "BB", "K", "HR"],
                    "athletes": [{
                        "athlete": {"displayName": "Tarik Skubal"},
                        "starter": True,
                        "notes": [{"type": "pitchingDecision", "text": "W, 6-5"}],
                        "stats": ["7.0", "5", "0", "0", "0", "9", "0"],
                    }],
                },
            ],
        }]},
    }

    rows = espn._parse_summary(summary, "MLB", datetime(2026, 7, 18).date())

    points = next(row for row in rows if row["player"] == "Tarik Skubal" and row["stat"] == "Points")
    hits = next(row for row in rows if row["player"] == "Test Hitter" and row["stat"] == "Hits")
    assert points["actual"] == 58
    assert hits["actual"] == 2


def test_espn_postponed_event_marks_matching_entry_leg_dnp(monkeypatch):
    monkeypatch.setattr(espn, "_scoreboard", lambda path, game_date: {
        "events": [{
            "competitions": [{
                "status": {"type": {"name": "STATUS_POSTPONED"}},
                "competitors": [
                    {"homeAway": "away", "team": {"abbreviation": "LAD"}},
                    {"homeAway": "home", "team": {"abbreviation": "NYY"}},
                ],
            }],
        }],
    })
    entries = [{"props": [
        {"player": "Shohei Ohtani", "team": "LAD", "sport": "MLB", "stat": "Hits", "game": "NYY", "game_time": "2026-07-19T00:08Z"},
        {"player": "Tarik Skubal", "team": "DET", "sport": "MLB", "stat": "Points", "game": "LAA", "game_time": "2026-07-19T02:07Z"},
    ]}]

    rows = espn.fetch_unplayed_entry_stats(entries, "MLB", datetime(2026, 7, 18).date())

    assert len(rows) == 1
    assert rows[0]["player"] == "Shohei Ohtani"
    assert rows[0]["status"] == "dnp"


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


def test_final_stats_do_not_use_only_player_row_from_wrong_game():
    rows = [
        SimpleNamespace(game="SEA@PHX", game_date="2026-07-14", id=1),
    ]

    assert _best_matching_row(rows, "IND", "SEA", target_date="2026-07-14") is None


def test_final_stats_recover_wrong_opponent_only_with_resolved_identity_context():
    rows = [
        SimpleNamespace(game="NY@LV", game_date="2026-07-30", id=1),
    ]

    matched = _best_matching_row(
        rows,
        "LAS",
        "NYL",
        target_date="2026-07-30",
        allow_unique_date_fallback=True,
    )

    assert matched.game == "NY@LV"


def test_prop_game_date_uses_eastern_calendar_date_for_utc_tipoff():
    assert _prop_game_date({"game_time": "2026-07-31T02:00:00Z"}) == "2026-07-30"


def test_unknown_leg_count_includes_projection_estimates():
    entries = [{
        "status": "Settled",
        "props": [{
            "actual": 22.0,
            "final_result": "Win",
            "final_source": "projection_estimate",
            "final_status": "estimated",
        }],
    }]

    assert web_app._unknown_entry_leg_count(entries) == 1


def test_final_stats_allow_adjacent_date_only_for_matching_game():
    rows = [
        SimpleNamespace(game="POR@LV", game_date="2026-07-29", id=1),
        SimpleNamespace(game="SEA@PHX", game_date="2026-07-29", id=2),
    ]

    matched = _best_matching_row(rows, "PDX", "LVA", target_date="2026-07-28")

    assert matched.game == "POR@LV"


def test_game_time_match_rejects_historical_candidate_before_entry():
    records = [{
        "sport": "WNBA",
        "parts": {"SEA", "IND"},
        "game_time": "2026-07-01T23:00:00Z",
        "starts_at": datetime(2026, 7, 1, 23, 0, tzinfo=UTC),
    }]

    matched = EntryRepository._best_game_time(
        records,
        "WNBA",
        {"SEA", "IND"},
        datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )

    assert matched == ""


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


def test_performance_insights_do_not_call_a_losing_platform_best():
    insights = dashboard_service._performance_insights({
        "by_platform": {
            "PrizePicks": {
                "wins": 1,
                "losses": 5,
                "profit": -40.0,
                "roi": -66.7,
            },
            "Underdog": {
                "wins": 2,
                "losses": 4,
                "profit": -10.0,
                "roi": -16.7,
            },
        },
    })

    platform_insight = next(
        insight for insight in insights
        if "platform" in insight["title"].lower()
    )
    assert platform_insight["title"] == "No profitable platform yet"
    assert "least-negative" in platform_insight["summary"]


def test_entry_primary_stat_uses_the_dominant_leg_market():
    entry = {
        "props": [
            {"stat": "Points"},
            {"stat": "Assists"},
            {"stat": "Points"},
        ],
    }

    assert EntryRepository._primary_stat(entry) == "Points"


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


def test_backtest_uses_joint_card_probability_and_verified_leg_calibration(monkeypatch):
    entries = [{
        "id": 1,
        "status": "Settled",
        "result": "Win",
        "average_confidence": 50.0,
        "wager": 10.0,
        "profit": 20.0,
        "props": [
            {"confidence": 50.0, "final_result": "Win", "final_source": "espn", "sport": "WNBA", "stat": "Points"},
            {"confidence": 50.0, "final_result": "Win", "final_source": "projection_estimate", "sport": "WNBA", "stat": "Assists"},
        ],
    }]
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)

    body = backtest()

    assert body["entries"]["confidence"]["average_card_probability"] == 25.0
    assert body["entries"]["confidence"]["average_leg_confidence"] == 50.0
    assert body["calibration_sources"]["prop_rows"] == 0
    assert body["calibration_sources"]["total_rows"] == 0
    assert sum(row["bets"] for row in body["entry_calibration"]) == 0


def test_backtest_reports_chronological_holdout_validation(monkeypatch):
    entries = []
    for index in range(25):
        entries.append({
            "id": index + 1,
            "status": "Settled",
            "result": "Win" if index % 4 == 0 else "Loss",
            "average_confidence": 50.0,
            "wager": 0.0,
            "profit": 0.0,
            "placed_at": datetime(2026, 6, 1) + timedelta(days=index),
            "props": [
                {"confidence": 50.0, "final_result": "Win", "final_source": "espn", "sport": "WNBA", "stat": "Points"},
                {"confidence": 50.0, "final_result": "Win", "final_source": "espn", "sport": "WNBA", "stat": "Assists"},
            ],
        })
    monkeypatch.setattr(web_app.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: entries)

    body = backtest()

    assert body["holdout_validation"]["ready"] is True
    assert body["holdout_validation"]["train_count"] == 15
    assert body["holdout_validation"]["holdout_count"] == 10
    assert "holdout_passed" in body["scorecard"]


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
    assert body["entries_targeted"] == 1
    assert body["backfill"]["backfilled"] == 1
    assert body["backfill"]["provider_rows"] == 1
    assert calls["entry_id"] == 7
    assert calls["legs"][0]["source"] == "sportsdataio"
    assert body["backtest"]["calibration_sources"]["entry_rows"] == 0


def test_portfolio_market_refresh_returns_updated_monitor(monkeypatch):
    pending = [{
        "id": 8,
        "status": "Pending",
        "entry_mode": "real",
        "platform": "PrizePicks",
        "props": [{
            "player": "A",
            "sport": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "platform": "PrizePicks",
            "game": "AAA @ BBB",
            "game_time": _today_game_time(),
        }],
    }]
    calls = []
    monkeypatch.setattr(web_app.EntryRepository, "pending", lambda: pending)
    monkeypatch.setattr(
        web_app,
        "_fetch_platform_props",
        lambda platform, force_refresh=False: calls.append((platform, force_refresh)) or [{"player": "A"}],
    )
    monkeypatch.setattr(
        web_app,
        "_portfolio_intelligence_payload",
        lambda: {"monitor": {"status_counts": {}, "entries": []}},
    )

    body = refresh_portfolio_market_data()

    assert calls == [("PrizePicks", True)]
    assert body["providers"][0]["status"] == "refreshed"
    assert body["intelligence"]["monitor"]["entries"] == []


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
    monkeypatch.setattr(
        web_app,
        "_quarantine_mismatched_settlement_evidence",
        lambda: {"detected": 2, "quarantined": 2, "entries": 1, "items": []},
    )

    body = recheck_entry_final_stats()

    assert body["unknown_before"] == 2
    assert body["unknown_after"] == 0
    assert body["cleared_unknowns"] == 2
    assert body["provider_refresh"]["imported"] == 2
    assert body["backfill"]["provider_rows"] == 1
    assert body["auto_check"]["settled"] == 1
    assert body["evidence_quarantine"]["quarantined"] == 2
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
    monkeypatch.setattr(web_app, "_quarantine_mismatched_settlement_evidence", lambda: {"detected": 0, "quarantined": 0, "entries": 0, "items": []})
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


def test_recheck_reports_result_after_dnp_rules(monkeypatch):
    entry = {"id": 22, "status": "Settled", "result": "Push", "props": [{"player": "A"}]}
    monkeypatch.setattr(
        web_app,
        "_evaluate_entry_result",
        lambda row, allow_estimates=False: {
            "settled": True,
            "result": "Win",
            "dnp_legs": 1,
            "legs": [],
            "message": "Settled from final stats.",
        },
    )
    monkeypatch.setattr(
        web_app.EntryRepository,
        "settle",
        lambda *args, **kwargs: {"id": 22, "result": "Push", "profit": 0.0},
    )

    result = web_app._recheck_entry_results([entry])

    assert result["corrected"] == 0
    assert result["entries"][0]["new_result"] == "Push"
    assert result["entries"][0]["changed"] is False
    assert "DNP" in result["entries"][0]["message"]


def test_recheck_recovers_excluded_entry_when_final_evidence_arrives(monkeypatch):
    entry = {"id": 23, "status": "Excluded", "result": "Unverifiable", "props": [{"player": "A"}]}
    stored = {}
    monkeypatch.setattr(
        web_app,
        "_evaluate_entry_result",
        lambda row, allow_estimates=False: {
            "settled": True,
            "result": "Win",
            "dnp_legs": 0,
            "legs": [{"player": "A", "result": "Win"}],
            "message": "Settled from final stats.",
        },
    )
    monkeypatch.setattr(
        web_app.EntryRepository,
        "settle",
        lambda entry_id, result, **kwargs: stored.update({"id": entry_id, "result": result}) or stored,
    )

    result = web_app._recheck_entry_results([entry])

    assert result["settled"] == 1
    assert result["corrected"] == 1
    assert stored == {"id": 23, "result": "Win"}


def test_missing_final_stat_is_not_labeled_provider_backed(monkeypatch):
    monkeypatch.setattr(web_app, "_usable_final_stat_for_entry", lambda prop, entry: None)
    entry = {
        "id": 31,
        "status": "Settled",
        "props": [
            {
                "player": "A",
                "sport": "WNBA",
                "stat": "Points",
                "line": 20.5,
                "direction": "Over",
            }
        ],
    }

    legs = web_app._entry_leg_final_snapshots(entry, allow_estimates=False)

    assert legs[0]["actual"] is None
    assert legs[0]["result"] == "Unknown"
    assert legs[0]["source"] == "unmatched"
    assert legs[0]["final_status"] == "unknown"


def test_completed_entry_refresh_uses_existing_loader():
    source = Path(web_app.__file__).with_name("static").joinpath("app.js").read_text(encoding="utf-8")

    assert "loadEntryHistory()" not in source
    assert "Promise.allSettled([loadBets(), loadEntryProgress" in source
    assert "data-inspect-opportunity" in source
    assert "selected.map(entryPropFromFeed)" in source
    assert "game_time: prop.game_time || \"\"" in source
    assert "A ranked prop is research, not a cleared paid card" in source
    assert "recommended_by_app: Boolean(state.recommendationOrigin)" in source
    assert "tracking_override_allowed" in source
    assert "You can still press Place Paid Entry to track your decision" in source


def test_notification_timing_alerts_reuse_cached_briefing(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_cached_daily_briefing_payload",
        lambda *args, **kwargs: {
            "sections": {
                "bet": [
                    {
                        "title": "Best card",
                        "score": 82,
                        "reason": "The line remains playable.",
                        "timing": {"label": "Take now", "severity": "positive", "score": 91},
                        "props": [{"player": "Test Player"}],
                    }
                ],
                "watch": [],
                "paper": [],
            }
        },
    )

    alerts = web_app._cached_briefing_timing_alerts()

    assert alerts == [
        {
            "type": "Take now",
            "severity": "positive",
            "player": "Test Player",
            "reason": "The line remains playable.",
            "priority_score": 91.0,
        }
    ]


def test_circuit_audio_is_offline_capable_and_user_controllable():
    static_dir = Path(web_app.__file__).with_name("static")
    index = static_dir.joinpath("index.html").read_text(encoding="utf-8")
    service_worker = static_dir.joinpath("sw.js").read_text(encoding="utf-8")
    audio = static_dir.joinpath("circuit-audio.js").read_text(encoding="utf-8")

    assert "/static/circuit-audio.js" in index
    assert 'id="pref-sound-effects"' in index
    assert 'id="pref-sound-volume"' in index
    assert '"/static/circuit-audio.js"' in service_worker
    assert "window.EdgeIQAudio = { play, save, settings }" in audio
    assert "new Audio(" not in audio


def test_place_entry_feedback_prevents_duplicate_submissions():
    static_dir = Path(web_app.__file__).with_name("static")
    source = static_dir.joinpath("app.js").read_text(encoding="utf-8")
    state_source = static_dir.joinpath("js", "state.js").read_text(encoding="utf-8")

    assert "placementInFlight: false" in state_source
    assert "if (state.placementInFlight || !state.lastEntryPayload) return false;" in source
    assert 'playCircuitSound("engage")' in source
    assert 'playCircuitSound("success")' in source
    assert 'playCircuitSound("warning")' in source
    assert 'placeEntryFromButton($("mobile-place-entry"))' in source


def test_semantic_button_sounds_cover_dynamic_controls_without_double_playback():
    static_dir = Path(web_app.__file__).with_name("static")
    app_source = static_dir.joinpath("app.js").read_text(encoding="utf-8")
    audio_source = static_dir.joinpath("circuit-audio.js").read_text(encoding="utf-8")

    for kind in ("tap", "navigate", "select", "scan", "inspect", "delete"):
        assert f'kind === "{kind}"' in audio_source
    assert "function buttonSoundKind(button)" in app_source
    assert "function setupButtonSounds()" in app_source
    assert 'button.matches(".circuit-action, #preview-sound")' in app_source
    assert "button.dataset.sound" in app_source
    assert 'button.matches(".danger, [data-remove-prop]")' in app_source
    assert "setupButtonSounds();" in app_source

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from data.providers import espn, prizepicks, underdog

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_espn_mlb_final_fixture_preserves_identity_and_scoring() -> None:
    summary = json.loads((FIXTURE_DIR / "espn_mlb_final.json").read_text(encoding="utf-8"))

    rows = espn._parse_summary(summary, "MLB", date(2026, 7, 18))

    points = next(row for row in rows if row["player"] == "Tarik Skubal" and row["stat"] == "Points")
    hits = next(row for row in rows if row["player"] == "Test Hitter" and row["stat"] == "Hits")
    assert points["actual"] == 58
    assert points["provider_player_id"] == "102"
    assert hits["actual"] == 2
    assert hits["provider_player_id"] == "101"


def test_espn_nfl_final_summary_supports_provider_markets() -> None:
    athlete = {"id": "nfl-1", "displayName": "Test Quarterback"}
    summary = {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": "ARI"}},
            {"homeAway": "home", "team": {"abbreviation": "CAR"}},
        ]}]},
        "boxscore": {"players": [{
            "team": {"abbreviation": "ARI"},
            "statistics": [
                {
                    "name": "passing",
                    "labels": ["C/ATT", "YDS", "AVG", "TD", "INT", "SACKS", "RTG"],
                    "athletes": [{"athlete": athlete, "stats": ["12/18", "164", "9.1", "2", "1", "2-11", "101.2"]}],
                },
                {
                    "name": "rushing",
                    "labels": ["CAR", "YDS", "AVG", "TD", "LONG"],
                    "athletes": [{"athlete": athlete, "stats": ["3", "21", "7.0", "1", "12"]}],
                },
                {
                    "name": "receiving",
                    "labels": ["REC", "YDS", "AVG", "TD", "LONG", "TGTS"],
                    "athletes": [{
                        "athlete": {"id": "nfl-2", "displayName": "Test Receiver"},
                        "stats": ["5", "73", "14.6", "1", "25", "7"],
                    }],
                },
                {
                    "name": "defensive",
                    "labels": ["TOT", "SOLO", "SACKS", "TFL", "PD", "QB HTS", "TD"],
                    "athletes": [{
                        "athlete": {"id": "nfl-3", "displayName": "Test Defender"},
                        "stats": ["4", "3", "1.5", "1", "0", "2", "0"],
                    }],
                },
                {
                    "name": "interceptions",
                    "labels": ["INT", "YDS", "TD"],
                    "athletes": [{
                        "athlete": {"id": "nfl-3", "displayName": "Test Defender"},
                        "stats": ["1", "18", "0"],
                    }],
                },
            ],
        }]},
    }

    rows = espn._parse_summary(summary, "NFL", date(2026, 8, 6))

    def actual(player: str, stat: str) -> float:
        return next(row["actual"] for row in rows if row["player"] == player and row["stat"] == stat)

    assert actual("Test Quarterback", "Pass Yards") == 164
    assert actual("Test Quarterback", "Pass TDs") == 2
    assert actual("Test Quarterback", "INTs Thrown") == 1
    assert actual("Test Quarterback", "Pass Attempts") == 18
    assert actual("Test Quarterback", "Rush Yards") == 21
    assert actual("Test Receiver", "Rec Yards") == 73
    assert actual("Test Receiver", "Rush + Rec Yards") == 73
    assert actual("Test Defender", "Sacks") == 1.5
    assert actual("Test Defender", "Tackles") == 4
    assert actual("Test Defender", "Tackles + Assists") == 4
    assert actual("Test Defender", "Defensive Interceptions") == 1
    assert next(row for row in rows if row["player"] == "Test Quarterback")["game"] == "ARI@CAR"
    assert next(row for row in rows if row["player"] == "Test Receiver")["provider_player_id"] == "nfl-2"


def test_prizepicks_fixture_preserves_offer_and_pra(monkeypatch) -> None:
    payload = json.loads((FIXTURE_DIR / "prizepicks_projection.json").read_text(encoding="utf-8"))
    request = {}
    monkeypatch.setattr(
        prizepicks,
        "get_json",
        lambda *args, **kwargs: request.update(kwargs) or SimpleNamespace(data=payload, stale=False, age_seconds=0),
    )

    row = prizepicks.fetch_projections()[0]

    assert row["player"] == "Azurá Stevens"
    assert row["player_id"] == "p1"
    assert row["stat"] == "Points + Rebounds + Assists"
    assert row["odds_type"] == "goblin"
    assert row["adjusted_odds"] is True
    assert row["game"] == "LAS @ NYL"
    assert row["game_time"] == "2026-07-25T19:00:00Z"
    assert row["provider_game_id"] == "WNBA_game_123"
    assert request["timeout"] == 10
    assert request["retries"] == 1


def test_prizepicks_duplicate_player_metadata_keeps_populated_fields() -> None:
    merged = prizepicks._merge_player_attrs(
        {"display_name": "NFL Player", "league": "NFL", "team": "ARI"},
        {"display_name": "", "league": "NFL", "team": ""},
    )

    assert merged == {"display_name": "NFL Player", "league": "NFL", "team": "ARI"}


def test_nfl_august_game_is_labeled_preseason_when_feed_omits_label() -> None:
    assert prizepicks._season_type("NFL", {}, {"start_time": "2026-08-06T20:00:00-04:00"}) == "preseason"
    assert underdog._season_type("NFL", {"scheduled_at": "2026-08-07T00:00:00Z"}, {}) == "preseason"


def test_espn_refresh_dates_use_the_eastern_slate_day() -> None:
    entries = [{
        "placed_at": datetime(2026, 8, 7, 2, 0),
        "props": [{"game_time": "2026-08-07T02:00:00Z"}],
    }]

    assert espn._entry_dates(entries) == [date(2026, 8, 6)]


def test_underdog_fixture_preserves_line_identity_and_game(monkeypatch) -> None:
    payload = json.loads((FIXTURE_DIR / "underdog_projection.json").read_text(encoding="utf-8"))
    request = {}
    monkeypatch.setattr(
        underdog,
        "get_json",
        lambda *args, **kwargs: request.update(kwargs) or SimpleNamespace(data=payload, stale=False, age_seconds=0),
    )

    row = underdog.fetch_projections()[0]

    assert row["player"] == "A'ja Wilson"
    assert row["player_id"] == "2"
    assert row["line"] == 22.5
    assert row["game"] == "LVA @ PHX"
    assert row["game_time"] == "2026-07-25T21:00:00Z"
    assert row["team"] == "LVA"
    assert row["match_id"] == "22"
    assert request["timeout"] == 10
    assert request["retries"] == 1


def test_underdog_team_uuid_is_normalized_from_matchup() -> None:
    game = {
        "away_team_id": "team-indiana-uuid",
        "home_team_id": "team-seattle-uuid",
    }

    assert underdog._team_abbreviation("team-indiana-uuid", "IND @ SEA", game) == "IND"
    assert underdog._team_abbreviation("team-seattle-uuid", "IND @ SEA", game) == "SEA"


def test_underdog_alternate_line_keeps_direction_and_payout() -> None:
    metadata = underdog._offer_metadata(
        {
            "line_type": "alternate",
            "options": [{
                "status": "active",
                "choice": "higher",
                "payout_multiplier": "1.25",
            }],
        },
        19.5,
        16.5,
    )

    assert metadata["direction"] == "Over"
    assert metadata["line_offer_type"] == "demon"
    assert metadata["is_premium_line"] is True
    assert metadata["payout_multiplier"] == 1.25


def test_underdog_balanced_line_does_not_force_the_first_active_side() -> None:
    metadata = underdog._offer_metadata(
        {
            "line_type": "balanced",
            "options": [{"status": "active", "choice": "higher"}],
        },
        19.5,
        19.5,
    )

    assert metadata["direction"] == ""
    assert metadata["line_offer_type"] == "standard"


def test_espn_marks_missing_tracked_player_dnp_after_exact_game_is_final() -> None:
    entries = [{"props": [{
        "player": "Bench Player",
        "team": "SD",
        "sport": "MLB",
        "stat": "Hits",
        "game": "SD @ AZ",
        "game_time": "2026-08-05T01:40:00Z",
    }]}]
    final_rows = [{
        "player": "Active Player",
        "team": "SD",
        "sport": "MLB",
        "stat": "Hits",
        "game": "SD@AZ",
        "game_date": "2026-08-05",
        "actual": 1,
        "status": "played",
    }]

    rows = espn.fetch_missing_entry_dnp_stats(entries, "MLB", date(2026, 8, 5), final_rows)

    assert rows == [{
        "player": "Bench Player",
        "team": "SD",
        "sport": "MLB",
        "stat": "Hits",
        "game": "SD@AZ",
        "game_date": "2026-08-05",
        "actual": 0.0,
        "status": "dnp",
        "source": "espn",
        "player_provider": "espn",
    }]

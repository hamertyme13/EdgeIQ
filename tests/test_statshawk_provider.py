from __future__ import annotations

from types import SimpleNamespace

from data.providers import statshawk

DAY = "2026-09-20"
CONTEST = {
    "id": "game-1", "status": "final", "kickoff": "2026-09-20T18:00:00Z",
    "away_team_name": "Indiana Fever", "away_team": "team-1",
    "home_team_name": "Washington Mystics", "home_team": "team-2",
}
BOX = {
    "data": {"contest": {"id": "game-1"}, "finalized": True, "lines": [{
        "person": "player-1", "person_name": "Azurá Stevens", "team": "team-1",
        "phases": [{"phase": "basketball_player_game", "measures": {
            "min": 31, "pts": 20, "reb": 8, "ast": 3, "fga": 15, "tpa": 6,
        }}],
    }]},
}


def _prop(stat="Points + Rebounds + Assists"):
    return {
        "player": "Azura Stevens", "team": "IND", "sport": "WNBA", "stat": stat,
        "game": "IND @ WAS", "game_time": "2026-09-20T18:00:00Z",
    }


def _setup(monkeypatch, contest=None, box=None, existing=None):
    monkeypatch.setenv("STATSHAWK_API_KEY", "test-key")
    monkeypatch.setattr(statshawk.FinalStatsRepository, "find_result", lambda _prop: existing)
    saved = []
    monkeypatch.setattr(statshawk.FinalStatsRepository, "upsert_many", lambda rows: saved.extend(rows) or len(rows))
    contest = CONTEST if contest is None else contest
    box = BOX if box is None else box
    monkeypatch.setattr(
        statshawk, "_request",
        lambda path, **_kwargs: box if "/boxscore" in path else {"data": {"items": [contest]}},
    )
    return saved


def test_imports_only_exact_final_game_player_team_and_stat(monkeypatch):
    saved = _setup(monkeypatch)
    result = statshawk.refresh_final_stats_for_entries([{"props": [_prop()]}])
    assert result["imported"] == 1
    assert result["contests_checked"] == 1
    assert saved[0]["actual"] == 31
    assert saved[0]["provider_player_id"] == "player-1"
    assert saved[0]["source"] == "statshawk"


def test_missing_measure_or_minutes_does_not_create_a_false_loss(monkeypatch):
    saved = _setup(monkeypatch)
    assert statshawk.refresh_final_stats_for_entries([{"props": [_prop("Blocks")]}])["imported"] == 0
    assert not saved
    assert statshawk._stat_value("WNBA", "Points", [{"phase": "basketball_player_game", "measures": {"min": 20, "pts": 0}}]) == 0
    assert not statshawk._played({"min": 0, "pts": 0})


def test_nonfinal_or_wrong_matchup_is_ignored(monkeypatch):
    saved = _setup(monkeypatch, contest={**CONTEST, "status": "live"})
    assert statshawk.refresh_final_stats_for_entries([{"props": [_prop()]}])["imported"] == 0
    assert not saved
    assert not statshawk._same_game({**_prop(), "game": "IND @ NYL"}, CONTEST, "WNBA", DAY)
    assert not statshawk._same_game({**_prop(), "game_time": "2026-09-20T02:00:00Z"}, CONTEST, "WNBA", DAY)


def test_doubleheader_requires_matching_start_time():
    contest = {
        "id": "game-2", "status": "final", "kickoff": "2026-09-20T22:00:00Z",
        "away_team_name": "New York Yankees", "home_team_name": "Boston Red Sox",
    }
    prop = {
        "game": "NYY @ BOS", "game_time": "2026-09-20T18:00:00Z",
    }
    assert not statshawk._same_game(prop, contest, "MLB", DAY)


def test_existing_verified_result_is_not_overwritten(monkeypatch):
    saved = _setup(monkeypatch, existing={"status": "played", "source": "espn"})
    result = statshawk.refresh_final_stats_for_entries([{"props": [_prop()]}])
    assert result["skipped"] is True
    assert not saved


def test_unconfigured_provider_is_optional(monkeypatch):
    monkeypatch.delenv("STATSHAWK_API_KEY", raising=False)
    monkeypatch.delenv("STATSHAWK_KEY", raising=False)
    result = statshawk.refresh_final_stats_for_entries([{"props": [_prop()]}])
    assert result["skipped"] is True
    assert result["imported"] == 0


def test_stale_response_cannot_settle(monkeypatch):
    monkeypatch.setenv("STATSHAWK_API_KEY", "test-key")
    monkeypatch.setattr(statshawk, "get_json", lambda *_args, **_kwargs: SimpleNamespace(data={"data": {}}, stale=True))
    try:
        statshawk._request("/contests/game-1/boxscore")
    except RuntimeError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale box scores must not settle props")


def test_baseball_batting_and_pitching_are_separate():
    phases = [
        {"phase": "batting", "measures": {"pa": 4, "h": 2, "b2": 1, "b3": 0, "hr": 0, "r": 1, "rbi": 2}},
        {"phase": "pitching", "measures": {"bf": 23, "pitches": 92, "so": 7, "outs": 18, "h": 4}},
    ]
    assert statshawk._stat_value("MLB", "Singles", phases) == 1
    assert statshawk._stat_value("MLB", "Hits + Runs + RBIs", phases) == 5
    assert statshawk._stat_value("MLB", "Pitcher Strikeouts", phases) == 7
    assert statshawk._stat_value("MLB", "Outs Recorded", phases) == 18
    assert statshawk._stat_value("MLB", "Earned Runs", phases) is None
    assert statshawk._stat_value("MLB", "Hits", [{"phase": "batting", "measures": {"pa": 0, "h": 0}}]) is None


def test_football_kicking_and_phase_qualified_yards():
    phases = [
        {"phase": "passing", "measures": {"yards": 220, "td": 2, "intc": 1}},
        {"phase": "rushing", "measures": {"yards": 32, "td": 1}},
        {"phase": "receiving", "measures": {"yards": 55, "td": 0}},
        {"phase": "kicking", "measures": {"xpm": 3, "xpa": 3, "fgm": 2, "fga": 2}},
    ]
    assert statshawk._stat_value("NFL", "Pass + Rush Yards", phases) == 252
    assert statshawk._stat_value("NCAAF", "Rush + Rec Yards", phases) == 87
    assert statshawk._stat_value("NFL", "Extra Points Made", phases) == 3
    assert statshawk._stat_value("NFL", "Interceptions Thrown", phases) == 1
    assert not statshawk._supported_stat("NFL", "Interceptions")
    assert not statshawk._supported_stat("NFL", "Sacks")
    assert statshawk._stat_value("NFL", "Rush + Rec Yards", phases[:2]) is None


def test_hockey_and_soccer_require_participation_and_correct_role():
    skater = [{"phase": "skater", "measures": {"toi_seconds": 900, "pts": 2, "sog": 4}}]
    goalie = [{"phase": "goalie", "measures": {"toi_seconds": 3600, "saves": 29}}]
    outfield = [{"phase": "outfield", "measures": {"minutes": 90, "shots": 3, "sot": 2}}]
    assert statshawk._stat_value("NHL", "Points", skater) == 2
    assert statshawk._stat_value("NHL", "Saves", goalie) == 29
    assert statshawk._stat_value("NHL", "Saves", skater) is None
    assert statshawk._stat_value("MLS", "Shots on Target", outfield) == 2
    assert statshawk._stat_value("EPL", "Shots", [{"phase": "outfield", "measures": {"minutes": 0, "shots": 0}}]) is None


def test_other_team_sports_settle_only_matched_final_boxscore(monkeypatch):
    contest = {
        "id": "mlb-game", "status": "final", "kickoff": "2026-09-20T18:00:00Z",
        "away_team_name": "New York Yankees", "away_team": "yankees",
        "home_team_name": "Boston Red Sox", "home_team": "red-sox",
    }
    box = {"data": {"contest": {"id": "mlb-game"}, "finalized": True, "lines": [{
        "person": "batter-1", "person_name": "Test Batter", "team": "yankees",
        "phases": [{"phase": "batting", "measures": {"pa": 4, "h": 2}}],
    }]}}
    saved = _setup(monkeypatch, contest=contest, box=box)
    prop = {
        "player": "Test Batter", "team": "NYY", "sport": "MLB", "stat": "Hits",
        "game": "NYY @ BOS", "game_time": "2026-09-20T18:00:00Z",
    }
    assert statshawk.refresh_final_stats_for_entries([{"props": [prop]}])["imported"] == 1
    assert saved[0]["actual"] == 2
    assert saved[0]["sport"] == "MLB"


def test_cross_year_and_same_year_competition_routes(monkeypatch):
    monkeypatch.setenv("STATSHAWK_API_KEY", "test-key")
    monkeypatch.setattr(statshawk.FinalStatsRepository, "find_result", lambda _prop: None)
    paths = []
    monkeypatch.setattr(
        statshawk,
        "_request",
        lambda path, **_kwargs: paths.append(path) or {"data": {"items": []}},
    )
    props = [
        {"player": "Player A", "team": "Boston Bruins", "sport": "NHL", "stat": "Shots on Goal",
         "game": "Boston Bruins @ Toronto Maple Leafs", "game_time": "2026-04-20T23:00:00Z"},
        {"player": "Player B", "team": "Texas Longhorns", "sport": "NCAAF", "stat": "Passing Yards",
         "game": "Texas Longhorns @ Oklahoma Sooners", "game_time": "2026-09-20T18:00:00Z"},
        {"player": "Player C", "team": "Manchester City", "sport": "EPL", "stat": "Shots",
         "game": "Manchester City @ Sunderland", "game_time": "2026-04-20T18:00:00Z"},
    ]
    statshawk.refresh_final_stats_for_entries([{"props": props}])
    assert any("/nhl/editions/2025/games" in path for path in paths)
    assert any("/ncaaf/editions/2026/games" in path for path in paths)
    assert any("/epl/editions/2025/games" in path for path in paths)

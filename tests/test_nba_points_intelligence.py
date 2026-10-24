from analytics.probabilistic_forecast import PropForecast
from data.providers import espn
from data.providers.espn import _event_season_type
from web.application.nba_points_intelligence import build_nba_points_intelligence


def team_game(day, game_id, home, away, home_points, away_points, *, source="espn_official_scoreboard", season_type="regular"):
    return {
        "game_id": game_id, "game_start": f"{day}T23:00:00Z", "source": source,
        "season_type": season_type,
        "home_team": home, "away_team": away,
        "home_aliases": [home], "away_aliases": [away],
        "actual_home_points": home_points, "actual_away_points": away_points,
        "actual_home_win": 1.0 if home_points > away_points else 0.0,
    }


def test_nba_opponent_defense_uses_only_prior_official_season_games():
    rows = [
        team_game("2026-10-18", "1", "NYK", "BOS", 100, 90),
        team_game("2026-10-19", "2", "CHI", "NYK", 115, 98),
        team_game("2026-10-20", "3", "NYK", "MIA", 110, 95, source="unverified"),
        team_game("2026-10-17", "preseason", "NYK", "MIA", 140, 70, season_type="preseason"),
        team_game("2026-10-24", "4", "NYK", "BOS", 120, 100),
        team_game("2026-03-20", "5", "NYK", "BOS", 70, 60),
    ]
    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-22T23:00:00Z", team_games=rows,
    )
    defense = result["matchup"]["team_points_allowed"]
    assert defense["sample_size"] == 2
    assert defense["last_10"] == 102.5
    assert defense["league_average"] == 100.8
    assert defense["defensive_rank"] is None
    assert defense["advantage_score"] is None
    assert len(defense["source_games"]) == 2
    assert defense["source_games"][0]["url"].endswith("/gameId/2")
    assert "Small" in defense["status"]
    assert "team points allowed available" in result["matchup"]["status"]


def test_nba_opponent_defense_matches_verified_provider_team_aliases():
    rows = [team_game("2026-10-20", "spurs-1", "SA", "OKC", 110, 100)]
    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="SAS",
        game_time="2026-10-22T23:00:00Z", team_games=rows,
    )
    assert result["matchup"]["team_points_allowed"]["last_10"] == 100.0


def game(day, points, game_name="BOS @ NYK", *, status="played", source="espn"):
    return {"game_date": day, "actual": points, "game": game_name, "team": "BOS", "status": status, "source": source}


def test_thresholds_custom_line_pushes_and_verified_current_season_only():
    history = [
        game("2026-10-20", 20), game("2026-10-18", 25), game("2026-10-16", 19),
        game("2026-10-14", 0, status="dnp"), game("2026-10-12", 30, source="import"),
        game("2026-10-11", None), game("2026-10-10", 50, source="projection_estimate"),
        game("2026-10-24", 35), game("2026-03-01", 22),
        game("2026-10-20", 20, source="nba_api"),
    ]
    result = build_nba_points_intelligence(history, line=20, forecast=None, opponent="NYK", game_time="2026-10-22T23:00:00Z")
    season = result["thresholds"]["season"]
    assert season["games"] == 3
    assert season["thresholds"][2]["hits"] == 2  # 20+ is inclusive.
    assert season["custom_line"]["hits"] == 1  # Over 20 excludes the push.
    assert season["custom_line"]["pushes"] == 1
    assert season["custom_line"]["decisions"] == 2
    assert season["custom_line"]["hit_rate"] == 50.0
    assert season["custom_line"]["average"] == 21.33
    assert result["matchup"]["head_to_head_games"] == 3
    assert result["matchup"]["advantage_score"] is None
    assert result["market"]["ev"] is None


def test_last_windows_home_away_and_small_sample_interval():
    history = [game(f"2026-10-{day:02d}", points, matchup) for day, points, matchup in [
        (20, 21, "BOS @ NYK"), (19, 22, "NYK @ BOS"), (18, 16, "BOS @ PHI"),
    ]]
    result = build_nba_points_intelligence(history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22")
    assert result["thresholds"]["last_5"]["custom_line"]["hits"] == 2
    assert result["thresholds"]["home"]["games"] == 1
    assert result["thresholds"]["away"]["games"] == 2
    assert result["thresholds"]["opponent"]["games"] == 2
    assert result["thresholds"]["last_5"]["custom_line"]["interval_95"][0] < 66.7
    assert result["data_quality"] == "Season unverified"


def test_market_prior_does_not_create_a_validated_probability():
    forecast = PropForecast(
        projection=19.5, probability=50, standard_deviation=0, sample_size=2,
        effective_sample_size=2, source="market_prior", model_version="market", paid_eligible=False,
        reason="thin", feature_as_of="2026-10-22T00:00:00Z", features={}, distribution={},
    )
    result = build_nba_points_intelligence(
        [game("2026-10-20", 24)], line=19.5, forecast=forecast,
        opponent="NYK", game_time="2026-10-22",
    )
    assert result["projection"]["expected_points"] is None
    assert result["projection"]["over_probability"] is None
    assert result["market"]["status"] == "No Validated Edge"


def test_rolling_baseline_uses_only_earlier_games():
    history = [game(f"2026-10-{day:02d}", value) for day, value in [
        (10, 10), (11, 10), (12, 10), (13, 10), (14, 10), (15, 20),
    ]]
    result = build_nba_points_intelligence(history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22")
    validation = result["validation"]
    assert validation["evaluated_games"] == 1
    assert validation["baselines"]["prior_5_average"]["mae"] == 10.0
    assert validation["baselines"]["prior_season_average"]["rmse"] == 10.0
    assert validation["brier_score"] is None


def test_minutes_challenger_uses_only_prior_verified_regular_season_games():
    history = [
        {**game(f"2026-10-{day:02d}", 20 if day < 12 else 30),
         "season_type": "regular", "verified_minutes": 20 if day < 12 else 30}
        for day in range(10, 17)
    ]
    history += [
        {**game("2026-10-17", 80), "season_type": "preseason", "verified_minutes": 40},
        {**game("2026-10-18", 60), "season_type": "regular", "minutes": 40},
        {**game("2026-10-24", 90), "season_type": "regular", "verified_minutes": 45},
    ]

    result = build_nba_points_intelligence(
        history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22T23:00:00Z",
    )["minutes_challenger"]

    assert result["sample_size"] == 7
    assert result["expected_minutes"] == 30.0
    assert result["points_per_minute"] == 1.0
    assert result["expected_points"] == 30.0
    assert result["validation"]["evaluated_games"] == 2
    assert result["validation"]["challenger"]["mae"] < result["validation"]["recent_points_average"]["mae"]
    assert result["probability"] is None


def test_minutes_challenger_with_fewer_than_five_verified_games_is_unavailable():
    history = [
        {**game(f"2026-10-{day:02d}", 20), "season_type": "regular", "verified_minutes": 30}
        for day in range(10, 14)
    ]
    result = build_nba_points_intelligence(
        history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22",
    )["minutes_challenger"]
    assert result["status"] == "insufficient_verified_minutes"
    assert result["expected_points"] is None


def test_preseason_is_excluded_and_unknown_season_is_disclosed():
    history = [
        {**game("2026-10-20", 22), "season_type": "regular"},
        {**game("2026-10-18", 31), "season_type": "preseason"},
        game("2026-10-16", 19),
    ]
    result = build_nba_points_intelligence(history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22")
    assert result["sample_size"] == 2
    assert result["season_provenance"] == {
        "regular_games": 1, "unverified_games": 1, "status": "season_type_unverified",
    }
    assert "not regular-season-only" in result["explanation"]
    assert result["thresholds"]["verified_season"]["games"] == 1
    assert result["thresholds"]["verified_season"]["custom_line"]["hits"] == 1


def test_verified_season_does_not_infer_unlabeled_games_are_regular():
    result = build_nba_points_intelligence(
        [game("2026-10-20", 25), game("2026-10-19", 17)],
        line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22",
    )

    assert result["thresholds"]["season"]["games"] == 2
    assert result["thresholds"]["verified_season"]["games"] == 0
    assert result["thresholds"]["verified_season"]["custom_line"]["hit_rate"] is None


def test_conflicting_verified_finals_are_withheld_instead_of_silently_picked():
    history = [
        {**game("2026-10-20", 25, "BOS @ NYK", source="espn"), "season_type": "regular"},
        {**game("2026-10-20", 29, "NYK vs BOS", source="nba_api"), "season_type": "regular"},
        {**game("2026-10-19", 22, "BOS @ PHI", source="espn"), "season_type": "regular"},
        {**game("2026-10-19", 22, "PHI @ BOS", source="statshawk"), "season_type": "regular"},
    ]
    result = build_nba_points_intelligence(history, line=20.5, forecast=None, opponent="NYK", game_time="2026-10-22")

    assert result["sample_size"] == 1
    assert result["thresholds"]["verified_season"]["custom_line"]["hits"] == 1
    assert result["data_reliability"]["excluded"]["conflicting_final"] == 2
    assert result["data_reliability"]["excluded"]["matching_duplicate"] == 1


def test_conflicting_finals_withhold_research_probability_even_with_a_verified_forecast():
    forecast = PropForecast(
        projection=24.0, probability=65.0, standard_deviation=5.0, sample_size=10,
        effective_sample_size=10, source="verified_history_distribution", model_version="test",
        paid_eligible=False, reason="research", feature_as_of="2026-10-21T00:00:00Z",
        features={}, distribution={},
    )
    history = [
        {**game("2026-10-20", 25, source="espn"), "season_type": "regular"},
        {**game("2026-10-20", 29, source="nba_api"), "season_type": "regular"},
    ]
    result = build_nba_points_intelligence(
        history, line=20.5, forecast=forecast, opponent="NYK", game_time="2026-10-22",
    )

    assert result["projection"]["expected_points"] is None
    assert result["projection"]["over_probability"] is None
    assert "stored finals disagree" in result["projection"]["note"]


def test_missing_matchup_implausible_points_and_season_conflicts_are_visible():
    history = [
        {**game("2026-10-20", 25, "BOS @ NYK"), "season_type": "regular"},
        {**game("2026-10-20", 25, "BOS @ NYK", source="nba_api"), "season_type": "preseason"},
        game("2026-10-19", 20, ""),
        game("2026-10-18", 120, "BOS @ PHI"),
    ]
    result = build_nba_points_intelligence(history, line=20.5, forecast=None, opponent="NYK", game_time="2026-10-22")

    assert result["sample_size"] == 0
    assert result["data_reliability"]["excluded"] == {
        "conflicting_season_type": 2,
        "implausible_points": 1,
        "missing_matchup": 1,
    }


def test_inactive_and_unfinished_games_never_count_as_scoring_decisions():
    history = [
        {**game("2026-10-20", 0, status="dnp"), "season_type": "regular"},
        {**game("2026-10-19", 0, status="scheduled"), "season_type": "regular"},
        {**game("2026-10-18", 21), "season_type": "regular"},
    ]
    result = build_nba_points_intelligence(
        history, line=20.5, forecast=None, opponent="NYK", game_time="2026-10-22",
    )

    assert result["sample_size"] == 1
    assert result["thresholds"]["verified_season"]["custom_line"]["decisions"] == 1
    assert result["data_reliability"]["excluded"]["not_played"] == 2


def test_missing_team_provider_history_does_not_invent_matchup_or_market_edge():
    result = build_nba_points_intelligence(
        [{**game("2026-10-20", 24), "season_type": "regular"}],
        line=20.5, forecast=None, opponent="NYK", game_time="2026-10-22",
        team_games=None,
    )

    assert result["matchup"]["team_points_allowed"]["sample_size"] == 0
    assert result["matchup"]["advantage_score"] is None
    assert result["projection"]["over_probability"] is None
    assert result["market"]["ev"] is None


def test_espn_season_type_never_guesses_from_date_or_opaque_number():
    assert _event_season_type({"season": {"slug": "regular-season"}}) == "regular"
    assert _event_season_type({"season": {"displayName": "Preseason"}}) == "preseason"
    assert _event_season_type({"season": {"displayName": "Postseason"}}) == "postseason"
    assert _event_season_type({"season": {"type": 2}}) is None


def test_official_team_score_preserves_season_type(monkeypatch):
    from datetime import date

    event = {
        "id": "nba-final-1",
        "date": "2026-10-20T23:00:00Z",
        "season": {"slug": "regular-season"},
        "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"homeAway": "home", "score": "102", "team": {"displayName": "Boston Celtics", "abbreviation": "BOS"}},
                {"homeAway": "away", "score": "98", "team": {"displayName": "New York Knicks", "abbreviation": "NYK"}},
            ],
        }],
    }
    monkeypatch.setattr(espn, "_scoreboard", lambda *_args: {"events": [event]})

    outcomes = espn.fetch_final_game_outcomes("NBA", date(2026, 10, 20))

    assert len(outcomes) == 1
    assert outcomes[0]["season_type"] == "regular"
    assert outcomes[0]["source"] == "espn_official_scoreboard"

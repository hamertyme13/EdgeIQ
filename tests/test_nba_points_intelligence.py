from datetime import UTC, datetime, timedelta

from analytics.probabilistic_forecast import PropForecast
from data.providers import espn
from data.providers.espn import _event_season_type
from web.application.nba_points_intelligence import build_nba_points_intelligence, verified_opponent_injury_context


def test_opponent_injury_context_requires_exact_team_source_and_fresh_pregame_capture():
    now = datetime(2026, 11, 9, 16, tzinfo=UTC)
    report = {"player": "Opponent Player", "team": "NY", "status": "Questionable",
              "source": "espn_injury_feed", "verified": True,
              "captured_at": (now - timedelta(minutes=5)).isoformat()}
    result = verified_opponent_injury_context(
        "NYK", "2026-11-09T23:00:00Z", [report, {**report, "team": "BOS"}], now=now,
    )
    assert result["status"] == "reported"
    assert len(result["reports"]) == 1
    assert result["reports"][0]["player"] == "Opponent Player"
    assert verified_opponent_injury_context(
        "NYK", "2026-11-09T23:00:00Z",
        [{**report, "captured_at": (now - timedelta(hours=2)).isoformat()}], now=now,
    )["status"] == "unavailable"
    assert verified_opponent_injury_context(
        "NYK", "2026-11-09T15:00:00Z", [report], now=now,
    )["status"] == "unavailable"


def test_research_availability_reuses_one_injury_fetch_for_opponent(monkeypatch):
    from web import app as web_app

    calls = []

    def injury_feed(sport):
        calls.append(sport)
        return [{"player": "Opponent Player", "team": "NY", "status": "Questionable",
                 "source": "espn_injury_feed", "verified": True,
                 "captured_at": datetime.now(UTC).isoformat()}]

    monkeypatch.setattr(web_app, "fetch_injuries", injury_feed)
    monkeypatch.setattr(web_app.newsapi, "fetch_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(web_app.newsapi, "risk_terms", lambda *_args: [])
    result = web_app._player_availability_payload("Research Guard", "NBA", "BOS", "BOS @ NYK")
    assert calls == ["NBA"]
    assert len(result["opponent_injury_reports"]) == 1
    assert result["status"] == "Likely Active"


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
    assert defense["home_sample_size"] == 1
    assert defense["home_points_allowed_last_10"] == 90
    assert defense["away_sample_size"] == 1
    assert defense["away_points_allowed_last_10"] == 115
    assert defense["days_rest"] == 2
    assert defense["league_average"] is None
    assert defense["difference_from_league"] is None
    assert defense["defensive_rank"] is None
    assert defense["advantage_score"] is None
    assert len(defense["source_games"]) == 2
    assert defense["source_games"][0]["url"].endswith("/gameId/2")
    assert "Small" in defense["status"]
    assert "enough comparable verified games" in result["matchup"]["status"]


def test_nba_opponent_rest_uses_eastern_game_dates_and_pregame_official_results():
    previous = team_game("2026-10-22", "late", "NYK", "BOS", 100, 90)
    previous["game_start"] = "2026-10-23T02:00:00Z"  # October 22 in New York.
    future = team_game("2026-10-23", "future", "NYK", "BOS", 130, 120)
    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-23T23:00:00Z", team_games=[previous, future],
    )
    defense = result["matchup"]["team_points_allowed"]
    assert defense["sample_size"] == 1
    assert defense["days_rest"] == 0
    assert defense["home_points_allowed_last_10"] == 90
    assert defense["away_points_allowed_last_10"] is None


def test_nba_opponent_defense_matches_verified_provider_team_aliases():
    rows = [team_game("2026-10-20", "spurs-1", "SA", "OKC", 110, 100)]
    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="SAS",
        game_time="2026-10-22T23:00:00Z", team_games=rows,
    )
    assert result["matchup"]["team_points_allowed"]["last_10"] == 100.0


def test_nba_defense_comparison_requires_coverage_and_uses_only_pregame_regular_games():
    rows = []
    for day in range(16, 21):
        for index in range(5):
            rows.append(team_game(
                f"2026-10-{day}", f"{day}-{index}", f"T{index}", f"T{index + 5}",
                100, 130 if index == 0 else 100,
            ))
    rows.append(team_game("2026-10-22", "future", "T0", "T5", 70, 50))
    rows.append(team_game("2026-10-19", "preseason-extra", "T0", "T5", 70, 50, season_type="preseason"))
    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="T0",
        game_time="2026-10-21T23:00:00Z", team_games=rows,
    )
    matchup = result["matchup"]
    assert matchup["defensive_rank"] == 10
    assert matchup["advantage_score"] == 100
    assert matchup["team_points_allowed"]["ranked_teams"] == 10
    assert matchup["team_points_allowed"]["league_average"] is not None
    assert matchup["team_points_allowed"]["bottom_ten_defense"] is None
    assert matchup["team_points_allowed"]["last_5"] == 130
    assert result["projection"]["expected_points"] is None
    assert result["market"]["ev"] is None

    sparse = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="T0",
        game_time="2026-10-21T23:00:00Z", team_games=rows[:20],
    )["matchup"]
    assert sparse["advantage_score"] is None
    assert sparse["team_points_allowed"]["ranked_teams"] == 0


def test_nba_opponent_shooting_context_requires_five_complete_official_games():
    rows = []
    for day in range(16, 21):
        row = team_game(f"2026-10-{day}", f"shoot-{day}", "NYK", "BOS", 100, 90)
        row.update({"away_three_pointers_made": 12, "away_three_pointers_attempted": 30,
                    "away_points_in_paint": 40})
        rows.append(row)
    context = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-21T23:00:00Z", team_games=rows,
    )["matchup"]["team_points_allowed"]["shooting_allowed"]
    assert context["status"] == "descriptive_official_box_scores"
    assert context["three_point_pct"] == 40.0
    assert context["paint_points_per_game"] == 40.0
    assert build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-21T23:00:00Z", team_games=rows[:4],
    )["matchup"]["team_points_allowed"]["shooting_allowed"]["status"] == "unavailable"


def test_bottom_ten_defense_requires_full_league_coverage():
    rows = [team_game(
        f"2026-10-{day}", f"{day}-{index}", f"T{index}", f"T{index + 15}",
        100, 140 if index == 0 else 100,
    ) for day in range(16, 21) for index in range(15)]
    defense = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="T0",
        game_time="2026-10-21T23:00:00Z", team_games=rows,
    )["matchup"]["team_points_allowed"]
    assert defense["ranked_teams"] == 30
    assert defense["bottom_ten_defense"] is True


def test_nba_pace_rank_needs_five_complete_official_games_for_ten_teams():
    rows = []
    for day in range(16, 21):
        for index in range(5):
            row = team_game(f"2026-10-{day}", f"pace-{day}-{index}",
                            f"T{index}", f"T{index + 5}", 100, 95)
            row["pace"] = 94 + index * 2
            rows.append(row)
    future = team_game("2026-10-22", "future-pace", "T4", "T9", 100, 95)
    future["pace"] = 140
    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="T4",
        game_time="2026-10-21T23:00:00Z", team_games=[*rows, future],
    )
    comparison = result["matchup"]["team_points_allowed"]["pace_comparison"]
    assert comparison["status"] == "descriptive_comparison"
    assert comparison["ranked_teams"] == 10
    assert comparison["opponent_pace_last_5"] == 102
    assert comparison["league_pace_average"] == 98
    assert comparison["pace_rank_fastest_first"] == 1
    assert comparison["pace_percentile"] == 94

    rows[0]["pace"] = None
    sparse = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="T4",
        game_time="2026-10-21T23:00:00Z", team_games=rows,
    )["matchup"]["team_points_allowed"]["pace_comparison"]
    assert sparse["status"] == "unavailable"
    assert sparse["ranked_teams"] < 10


def test_nba_defense_rank_resolves_provider_alias_to_verified_team_name():
    rows = []
    for day in range(16, 21):
        for index in range(5):
            row = team_game(
                f"2026-10-{day}", f"{day}-{index}",
                "Orlando Magic" if index == 0 else f"T{index}",
                f"T{index + 5}", 100, 130 if index == 0 else 100,
            )
            if index == 0:
                row["home_aliases"].append("ORL")
            rows.append(row)
    matchup = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="ORL",
        game_time="2026-10-21T23:00:00Z", team_games=rows,
    )["matchup"]
    assert matchup["team_points_allowed"]["sample_size"] == 5
    assert matchup["team_points_allowed"]["ranked_teams"] == 10
    assert matchup["defensive_rank"] == 10
    assert matchup["team_points_allowed"]["rank_unavailable_reason"] is None


def test_nba_opponent_pace_uses_only_plausible_prior_regular_box_scores():
    prior = team_game("2026-10-20", "pace-1", "NYK", "BOS", 110, 100)
    prior["pace"] = 98.4
    invalid = team_game("2026-10-19", "pace-2", "CHI", "NYK", 102, 99)
    invalid["pace"] = 300
    preseason = team_game("2026-10-18", "pace-3", "NYK", "MIA", 120, 90, season_type="preseason")
    preseason["pace"] = 120
    later = team_game("2026-10-24", "pace-4", "NYK", "BOS", 115, 105)
    later["pace"] = 110

    result = build_nba_points_intelligence(
        [], line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-22T23:00:00Z", team_games=[prior, invalid, preseason, later],
    )
    pace = result["matchup"]["team_points_allowed"]
    assert pace["pace_sample_size"] == 1
    assert pace["pace_last_5"] == 98.4
    assert pace["pace_source"] == "espn_box_score_possessions"


def game(day, points, game_name="BOS @ NYK", *, status="played", source="espn"):
    return {"game_date": day, "actual": points, "game": game_name, "team": "BOS", "status": status, "source": source}


def test_recent_verified_final_evidence_excludes_unlabeled_and_future_games():
    regular = {**game("2026-10-20", 23), "season_type": "regular"}
    unlabeled = game("2026-10-19", 50, "BOS @ CHI")
    future = {**game("2026-10-24", 30, "BOS @ MIA"), "season_type": "regular"}
    result = build_nba_points_intelligence(
        [regular, unlabeled, future], line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-22T23:00:00Z",
    )
    assert result["recent_verified_finals"] == [{
        "game_date": "2026-10-20", "game": "BOS @ NYK", "points": 23.0,
        "source": "espn", "imported_at": None,
    }]


def test_late_eastern_tip_does_not_include_same_day_final():
    history = [
        game("2026-10-22", 32),
        game("2026-10-21", 18),
    ]
    result = build_nba_points_intelligence(
        history, line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-23T02:30:00Z",
    )
    assert result["sample_size"] == 1
    assert result["thresholds"]["season"]["custom_line"]["hits"] == 0
    assert result["data_reliability"]["excluded"]["outside_pregame_season"] == 1


def test_pregame_replay_withholds_finals_imported_after_tipoff():
    history = [
        {**game("2026-10-20", 20, "BOS @ NYK"), "imported_at": "2026-10-22T22:00:00Z"},
        {**game("2026-10-21", 26, "BOS @ PHI"), "imported_at": "2026-10-23T01:00:00Z"},
        {**game("2026-10-19", 30, "BOS @ MIA"), "imported_at": "invalid"},
    ]
    result = build_nba_points_intelligence(
        history, line=19.5, forecast=None, opponent="NYK",
        game_time="2026-10-22T23:00:00Z",
    )
    assert result["sample_size"] == 1
    assert result["thresholds"]["season"]["custom_line"]["hits"] == 1
    assert result["data_reliability"]["excluded"]["imported_after_tipoff"] == 1
    assert result["data_reliability"]["excluded"]["invalid_import_timestamp"] == 1


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
    assert result["thresholds"]["home"]["unverified_games"] == 1
    assert result["thresholds"]["away"]["unverified_games"] == 2
    assert result["thresholds"]["last_5"]["custom_line"]["interval_95"][0] < 66.7
    assert result["data_quality"] == "Season unverified"


def test_scoring_splits_report_provenance_for_their_own_games():
    history = [
        {**game("2026-10-20", 22, "BOS @ NYK"), "season_type": "regular"},
        game("2026-10-19", 17, "NYK @ BOS"),
        {**game("2026-10-18", 28, "BOS @ PHI"), "season_type": "regular"},
    ]
    result = build_nba_points_intelligence(history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22")
    assert result["thresholds"]["away"]["regular_games"] == 2
    assert result["thresholds"]["away"]["unverified_games"] == 0
    assert result["thresholds"]["opponent"]["regular_games"] == 1
    assert result["thresholds"]["opponent"]["unverified_games"] == 1
    assert result["thresholds"]["home"]["unverified_games"] == 1


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
    assert result["projection"]["observed_scoring_spread"] is None
    assert result["market"]["status"] == "No Validated Edge"


def test_verified_forecast_exposes_observed_spread_without_claiming_prediction_interval():
    forecast = PropForecast(
        projection=24.0, probability=60, standard_deviation=5, sample_size=10,
        effective_sample_size=8, source="verified_history_distribution", model_version="test",
        paid_eligible=False, reason="research", feature_as_of="2026-10-21T00:00:00Z",
        features={}, distribution={
            "floor": 12, "percentile_25": 18, "median": 23,
            "percentile_75": 28, "ceiling": 34,
            "uncertainty_level": "High", "uncertainty_drivers": ["Minutes vary"],
        },
    )
    history = [{**game("2026-10-20", 25), "season_type": "regular"}]
    projection = build_nba_points_intelligence(
        history, line=20.5, forecast=forecast, opponent="NYK", game_time="2026-10-22",
    )["projection"]

    assert projection["observed_scoring_spread"]["p25"] == 18
    assert projection["observed_scoring_spread"]["p90"] == 34
    assert "not a calibrated next-game prediction interval" in projection["observed_scoring_spread"]["label"]
    assert projection["uncertainty_drivers"] == ["Minutes vary"]


def test_rolling_baseline_uses_only_earlier_games():
    history = [{**game(f"2026-10-{day:02d}", value), "season_type": "regular"} for day, value in [
        (10, 10), (11, 10), (12, 10), (13, 10), (14, 10), (15, 20),
    ]]
    result = build_nba_points_intelligence(history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22")
    validation = result["validation"]
    assert validation["evaluated_games"] == 1
    assert validation["baselines"]["prior_5_average"]["mae"] == 10.0
    assert validation["baselines"]["prior_season_average"]["rmse"] == 10.0
    assert validation["brier_score"] is None


def test_rolling_baseline_excludes_season_unverified_history():
    history = [{**game(f"2026-10-{day:02d}", 20), "season_type": "regular"} for day in range(10, 16)]
    history.append(game("2026-10-16", 80))

    result = build_nba_points_intelligence(
        history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22",
    )

    assert result["thresholds"]["season"]["games"] == 7
    assert result["thresholds"]["verified_season"]["games"] == 6
    assert result["validation"]["evaluated_games"] == 1
    assert result["validation"]["baselines"]["prior_5_average"]["mae"] == 0.0
    assert result["validation"]["baselines"]["prior_season_average"]["mae"] == 0.0


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


def test_zero_points_without_verified_minutes_do_not_count_as_played_scoring_history():
    history = [
        {**game("2026-10-20", 0), "season_type": "regular"},
        {**game("2026-10-19", 0), "season_type": "regular", "verified_minutes": 8},
        {**game("2026-10-18", 20), "season_type": "regular"},
    ]

    result = build_nba_points_intelligence(
        history, line=19.5, forecast=None, opponent="NYK", game_time="2026-10-22",
    )

    assert result["sample_size"] == 2
    assert result["data_reliability"]["excluded"]["participation_unverified"] == 1
    assert result["thresholds"]["verified_season"]["custom_line"]["hits"] == 1


def test_zero_points_with_verified_shot_attempt_still_count():
    result = build_nba_points_intelligence(
        [{**game("2026-10-20", 0), "season_type": "regular", "verified_field_goals_attempted": 1}],
        line=0.5, forecast=None, opponent="NYK", game_time="2026-10-22",
    )

    assert result["sample_size"] == 1
    assert result["data_reliability"]["excluded"].get("participation_unverified", 0) == 0


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
    assert result["projection"]["observed_scoring_spread"] is None
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

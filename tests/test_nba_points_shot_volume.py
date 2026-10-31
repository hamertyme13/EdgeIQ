from analytics.nba_points_shot_volume import shot_volume_challenger


def game(day, points, field_goals, free_throws, *, source="espn", season_type="regular"):
    return {
        "game_date": f"2026-10-{day:02d}", "actual": points,
        "verified_field_goals_attempted": field_goals,
        "verified_free_throws_attempted": free_throws,
        "source": source, "season_type": season_type,
    }


def test_shot_volume_challenger_uses_only_prior_verified_regular_season_games():
    history = [game(day, 20 if day < 16 else 30, 10, 5) for day in range(10, 18)]
    history += [game(19, 90, 50, 10, season_type="preseason"), game(20, 90, 50, 10, source="manual")]
    history = list(reversed(history))

    result = shot_volume_challenger(history)

    assert result["sample_size"] == 8
    assert result["expected_attempts"] == 15
    assert result["expected_points"] == 22.5
    assert result["validation"]["evaluated_games"] == 3
    assert result["validation"]["challenger"]["mae"] is not None
    assert result["probability"] is None
    assert result["shadow_only"] is True


def test_shot_volume_challenger_withholds_incomplete_or_implausible_attempts():
    history = [game(day, 25, 14, 6) for day in range(10, 14)]
    history += [game(14, 80, 61, 1), game(15, 30, 10, None)]

    result = shot_volume_challenger(list(reversed(history)))

    assert result["sample_size"] == 4
    assert result["status"] == "insufficient_verified_shot_volume"
    assert result["expected_points"] is None

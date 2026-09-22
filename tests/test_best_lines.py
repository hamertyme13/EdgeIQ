from web.application.best_lines_service import best_lines_payload


def row(platform, line, **extra):
    return {"platform": platform, "line": line, "line_offer_type": "standard",
            "sport": "WNBA", "stat": "Points", "game": "AAA @ BBB",
            "game_time": "2026-09-12T20:00:00Z", **extra}


def test_direction_specific_thresholds_and_ties():
    data = {"lines": [row("PrizePicks", 20), row("Underdog", 21), row("Sleeper", 20)]}
    over = best_lines_payload(data)["lines"]
    under = best_lines_payload(data, "Under")["lines"]
    assert [x["best_threshold"] for x in over] == [True, False, True]
    assert [x["best_threshold"] for x in under] == [False, True, False]
    assert "best_threshold" not in data["lines"][0]


def test_different_games_and_start_times_cannot_compete():
    data = {"lines": [row("PrizePicks", 20), row("Underdog", 21, game="AAA @ CCC"),
                      row("Sleeper", 22, game_time="2026-09-13T20:00:00Z")]}
    assert not any(x["best_threshold"] for x in best_lines_payload(data)["lines"])


def test_adjusted_and_direction_restricted_offers_are_not_best():
    data = {"lines": [row("PrizePicks", 30, line_offer_type="demon"),
                      row("Underdog", 22, allowed_directions=["Over"]),
                      row("Sleeper", 21), row("Pick6", 25, adjusted_line=True)]}
    result = best_lines_payload(data, "Under")
    assert not any(x["best_threshold"] for x in result["lines"])
    assert [x["comparable"] for x in result["lines"]] == [False, False, True, False]


def test_missing_game_identity_and_invalid_lines_are_not_ranked():
    data = {"lines": [row("A", 20, game_time=""), row("B", 21, game=""), row("C", float("nan"))]}
    result = best_lines_payload(data)
    assert len(result["lines"]) == 2
    assert not any(x["best_threshold"] for x in result["lines"])


def test_equivalent_timezone_offsets_group_together():
    data = {"lines": [row("A", 20), row("B", 21, game_time="2026-09-12T16:00:00-04:00")]}
    assert best_lines_payload(data)["lines"][0]["best_threshold"]

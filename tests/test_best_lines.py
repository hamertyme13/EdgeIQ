import pytest

from web.application.best_lines_service import best_lines_payload
from web.routers.market import MarketDependencies, browse_best_lines


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


@pytest.mark.parametrize("allowed", [[], None, "Over", {"Over": True}])
def test_explicit_invalid_or_empty_restrictions_never_enable_directions(allowed):
    for direction in ("Over", "Under"):
        data = {"lines": [row("A", 20, allowed_directions=allowed), row("B", 21)]}
        result = best_lines_payload(data, direction)["lines"]
        assert result[0]["allowed_directions"] == []
        assert not result[0]["comparable"]
        assert not any(item["best_threshold"] for item in result)


def test_premium_offer_does_not_override_explicit_empty_restriction():
    data = {"lines": [row("PrizePicks", 20, line_offer_type="demon", allowed_directions=[])]}
    assert best_lines_payload(data)["lines"][0]["allowed_directions"] == []


def test_different_players_cannot_be_compared_in_browse():
    data = {"lines": [row("PrizePicks", 20, player="Player A"),
                      row("Underdog", 21, player="Player B")]}
    assert not any(item["best_threshold"] for item in best_lines_payload(data)["lines"])


def test_browse_is_bounded_to_cached_future_offers():
    from datetime import UTC, datetime, timedelta

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    offers = [row("PrizePicks", 20, player=f"Player {i}", game_time=future,
                  league="WNBA", trending_count=100 - i) for i in range(60)]
    offers.append(row("PrizePicks", 20, player="Past", game_time=past, league="WNBA"))
    deps = MarketDependencies(
        line_shop=lambda *args: {}, cached_props=lambda platform, sport: offers,
        capture_offers=lambda rows: rows,
        sharp_consensus=lambda *args: {}, hedge_calculator=lambda value: {},
        middle_calculator=lambda value: {}, boost_analysis=lambda value: {},
        ev_scanner=lambda *args: [], timing_alerts=lambda *args: [], clv_report=lambda: {},
    )
    result = browse_best_lines("WNBA", deps=deps)
    assert result["total_matching"] == 60
    assert len(result["lines"]) == 50
    assert all(item["player"] != "Past" for item in result["lines"])

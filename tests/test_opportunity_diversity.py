from web.application.opportunity_presentation import best_offer_per_market, best_offer_per_player


def test_best_offer_per_market_prefers_score_then_standard_line() -> None:
    base = {"sport": "WNBA", "player": "A'ja Wilson", "stat": "Points",
            "game": "Aces@Storm", "platform": "PrizePicks", "confidence": 70}
    rows = [
        {**base, "line": 24.5, "score": 81, "adjusted_line": False},
        {**base, "line": 20.5, "score": 79, "adjusted_line": True},
        {**base, "line": 26.5, "score": 81, "adjusted_line": True},
        {**base, "player": "Breanna Stewart", "line": 18.5, "score": 75},
    ]

    selected = best_offer_per_market(rows)

    assert len(selected) == 2
    assert selected[0]["line"] == 24.5
    assert selected[1]["player"] == "Breanna Stewart"


def test_best_offer_per_market_keeps_distinct_games_and_providers() -> None:
    base = {"sport": "WNBA", "player": "A'ja Wilson", "stat": "Points", "line": 24.5}
    rows = [
        {**base, "game": "Aces@Storm", "platform": "PrizePicks", "score": 80},
        {**base, "game": "Aces@Storm", "platform": "Underdog", "score": 79},
        {**base, "game": "Aces@Liberty", "platform": "PrizePicks", "score": 78},
    ]

    assert len(best_offer_per_market(rows)) == 3


def test_best_offer_per_player_keeps_highest_scored_stat_and_normalizes_name() -> None:
    rows = [
        {"sport": "WNBA", "player": "Azurá Stevens", "stat": "Points", "score": 78},
        {"sport": "WNBA", "player": "Azura Stevens", "stat": "Rebounds", "score": 82},
        {"sport": "WNBA", "player": "Paige Bueckers", "stat": "Points", "score": 75},
    ]
    selected = best_offer_per_player(rows)
    assert len(selected) == 2
    assert selected[0]["stat"] == "Rebounds"

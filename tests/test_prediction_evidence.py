from analytics.prediction_evidence import deduplicate_outcomes, independent_market_key


def test_market_key_is_accent_insensitive_and_deduplicates_reused_legs() -> None:
    base = {
        "player": "Azurá Stevens",
        "sport": "WNBA",
        "stat": "Points",
        "line": 14.5,
        "direction": "Over",
        "game": "LAS @ NY",
        "game_time": "2026-07-25T19:00:00Z",
        "result": "Win",
        "final_source": "espn",
    }
    alias = {**base, "player": "Azura Stevens", "game": "NY @ LAS"}

    assert independent_market_key(base) == independent_market_key(alias)
    assert len(deduplicate_outcomes([base, alias])) == 1

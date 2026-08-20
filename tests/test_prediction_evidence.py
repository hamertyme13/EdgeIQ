from analytics.prediction_evidence import deduplicate_outcomes, independent_market_key, offer_key


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


def test_offer_key_preserves_provider_offer_identity() -> None:
    base = {
        "player": "Paige Bueckers",
        "provider_player_id": "pp-42",
        "sport": "WNBA",
        "stat": "Points",
        "line": 19.5,
        "standard_line": 19.5,
        "direction": "Over",
        "game": "MIN @ DAL",
        "game_time": "2026-08-13T20:00:00Z",
        "platform": "PrizePicks",
        "line_offer_type": "standard",
    }
    demon = {**base, "line": 22.5, "line_offer_type": "demon"}
    other_identity = {**base, "provider_player_id": "pp-99"}

    assert offer_key(base) != offer_key(demon)
    assert offer_key(base) != offer_key(other_identity)

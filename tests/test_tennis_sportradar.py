from data.providers import tennis_sportradar as tennis


def _summary(*, status="closed", reason=None, stats=None):
    return {
        "sport_event": {
            "id": "sr:sport_event:123", "start_time": "2026-10-19T17:00:00Z",
            "coverage": {"sport_event_properties": {"detailed_serve_outcomes": True, "scores": "live"}},
            "competitors": [
                {"id": "sr:competitor:1", "name": "Sinner, Jannik", "qualifier": "home"},
                {"id": "sr:competitor:2", "name": "Alcaraz, Carlos", "qualifier": "away"},
            ],
        },
        "sport_event_status": {"status": status, "winning_reason": reason},
        "statistics": {"totals": {"competitors": [
            {"id": "sr:competitor:1", "statistics": stats if stats is not None else
             {"aces": 10, "double_faults": 2, "games_won": 18}},
            {"id": "sr:competitor:2", "statistics": {"aces": 7}},
        ]}},
    }


def test_completed_match_preserves_player_match_and_exact_market():
    rows = tennis.parse_final_rows(_summary())
    assert {(row["player"], row["stat"], row["actual"]) for row in rows} == {
        ("Jannik Sinner", "Aces", 10),
        ("Jannik Sinner", "Double Faults", 2),
        ("Jannik Sinner", "Games Won", 18),
        ("Carlos Alcaraz", "Aces", 7),
    }
    assert all(row["game"] == "Jannik Sinner vs Carlos Alcaraz" for row in rows)
    assert all(row["game_date"] == "2026-10-19" for row in rows)


def test_retirement_or_unfinished_match_does_not_settle():
    assert tennis.parse_final_rows(_summary(reason="retirement")) == []
    assert tennis.parse_final_rows(_summary(status="live")) == []


def test_missing_market_value_is_not_inferred_as_zero():
    rows = tennis.parse_final_rows(_summary(stats={"aces": 0}))
    assert [(row["player"], row["stat"], row["actual"]) for row in rows
            if row["player"] == "Jannik Sinner"] == [("Jannik Sinner", "Aces", 0)]


def test_no_api_key_keeps_tennis_unavailable(monkeypatch):
    monkeypatch.delenv("SPORTRADAR_TENNIS_API_KEY", raising=False)
    assert not tennis.configured()
    assert tennis.refresh_final_stats_for_entries([{"props": [{"sport": "TENNIS"}]}])["skipped"]
    assert tennis.supported_market("Aces")
    assert not tennis.supported_market("Fantasy Score")


def test_offer_requires_exact_match_and_specific_coverage(monkeypatch):
    monkeypatch.setenv("SPORTRADAR_TENNIS_API_KEY", "test-key")
    summary = _summary(status="not_started")
    monkeypatch.setattr(tennis, "fetch_daily_summaries", lambda day: [summary])
    prop = {
        "player": "Jannik Sinner", "stat": "Aces",
        "game": "Carlos Alcaraz vs Jannik Sinner", "game_time": "2026-10-19T17:00:00Z",
    }
    assert tennis.offer_support(prop)[0]
    summary["sport_event"]["coverage"]["sport_event_properties"]["detailed_serve_outcomes"] = False
    assert not tennis.offer_support(prop)[0]
    prop["stat"] = "Games Won"
    assert tennis.offer_support(prop)[0]
    prop["game"] = "Jannik Sinner vs Another Player"
    assert not tennis.offer_support(prop)[0]

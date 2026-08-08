from web.application.recommendation_service import trending_props_payload


def test_trending_props_returns_top_15_by_full_grade() -> None:
    props = [
        {
            "player": f"Player {index}",
            "team": "AAA",
            "league": "WNBA",
            "stat": "Points",
            "line": 10.5,
            "game": "AAA@BBB",
            "game_time": "2026-08-06T19:00:00-04:00",
            "platform": "PrizePicks",
            "trending_count": 10_000 - index,
        }
        for index in range(20)
    ]

    def analyze(prop: dict) -> dict:
        index = int(str(prop["player"]).split()[-1])
        return {
            "direction": "Over",
            "projection": 12.0,
            "confidence": 50 + index,
            "data_quality": {"score": 60 + index},
            "data_strength": [],
            "hit_rate": {"sample_size": index},
            "forecast_paid_eligible": index >= 10,
        }

    payload = trending_props_payload(
        "PrizePicks",
        "WNBA",
        100,
        fetch_props=lambda platform, sport: props,
        analyze_prop=analyze,
        end_to_end_eligibility=lambda prop: {"eligible": True, "provider": "ESPN official box score"},
    )

    assert payload["count"] == 15
    assert payload["evaluated_count"] == 20
    assert payload["props"][0]["player"] == "Player 19"
    assert payload["props"][0]["rank"] == 1
    assert payload["props"][-1]["rank"] == 15


def test_trending_props_analyzes_only_small_eligible_pool() -> None:
    props = [
        {
            "player": f"Player {index}",
            "league": "NFL",
            "stat": "Receiving Yards",
            "line": 40.5,
            "game": "AAA@BBB",
            "game_time": "2026-08-06T19:00:00-04:00",
            "platform": "Underdog",
            "trending_count": 1_000 - index,
        }
        for index in range(80)
    ]
    analyzed: list[str] = []

    def analyze(prop: dict) -> dict:
        analyzed.append(prop["player"])
        return {
            "confidence": 55,
            "data_quality": {"score": 60},
            "hit_rate": {"sample_size": 5},
            "forecast_paid_eligible": False,
        }

    payload = trending_props_payload(
        "Underdog",
        "NFL",
        15,
        fetch_props=lambda platform, sport: props,
        analyze_prop=analyze,
        end_to_end_eligibility=lambda prop: {"eligible": True, "provider": "ESPN official box score"},
    )

    assert len(analyzed) == 30
    assert payload["evaluated_count"] == 30
    assert payload["eligible_count"] == 80
    assert payload["count"] == 15

from web.application.recommendation_service import trending_props_payload


def test_trending_props_selects_best_scored_line_per_market() -> None:
    offers = [
        {"player": "A'ja Wilson", "league": "WNBA", "stat": "Points", "game": "Aces@Storm",
         "platform": "PrizePicks", "line": line, "line_offer_type": offer_type,
         "trending_count": 100 - index}
        for index, (line, offer_type) in enumerate(((20.5, "goblin"), (25.5, "standard")))
    ]
    offers.append({"player": "Breanna Stewart", "league": "WNBA", "stat": "Rebounds",
                   "game": "Liberty@Fever", "platform": "PrizePicks", "line": 8.5})

    payload = trending_props_payload(
        "PrizePicks", "WNBA", 15, fetch_props=lambda *_: offers,
        analyze_prop=lambda prop: {
            "confidence": 82 if prop.get("line_offer_type") == "standard" else 60,
            "data_quality": {"score": 85}, "hit_rate": {"sample_size": 10},
            "forecast_paid_eligible": True,
        },
        end_to_end_eligibility=lambda _: {"eligible": True},
    )

    assert payload["evaluated_count"] == 3
    assert payload["count"] == 2
    assert next(row for row in payload["props"] if row["player"] == "A'ja Wilson")["line"] == 25.5


def test_trending_props_keeps_only_best_stat_for_player() -> None:
    offers = [
        {"player": "Veronica Burton", "league": "WNBA", "stat": stat,
         "game": "Aces@Storm", "platform": "PrizePicks", "line": line}
        for stat, line in (("Points", 12.5), ("Assists", 5.5))
    ]
    offers.append({"player": "Paige Bueckers", "league": "WNBA", "stat": "Points",
                   "game": "Wings@Lynx", "platform": "PrizePicks", "line": 19.5})
    payload = trending_props_payload(
        "PrizePicks", "WNBA", 15, fetch_props=lambda *_: offers,
        analyze_prop=lambda prop: {
            "confidence": 85 if prop["stat"] == "Assists" else 70,
            "data_quality": {"score": 85}, "hit_rate": {"sample_size": 20},
            "forecast_paid_eligible": True,
        },
        end_to_end_eligibility=lambda _: {"eligible": True},
    )
    assert payload["count"] == 2
    assert next(row for row in payload["props"] if row["player"] == "Veronica Burton")["stat"] == "Assists"


def test_trending_prefilter_does_not_spend_analysis_budget_on_one_player() -> None:
    offers = [
        {"player": "Player A", "league": "WNBA", "stat": f"Stat {index}",
         "game": "A@B", "platform": "PrizePicks", "line": 1.5,
         "trending_count": 10_000 - index}
        for index in range(30)
    ] + [
        {"player": f"Player {index}", "league": "WNBA", "stat": "Points",
         "game": "A@B", "platform": "PrizePicks", "line": 10.5,
         "trending_count": 100 - index}
        for index in range(15)
    ]
    payload = trending_props_payload(
        "PrizePicks", "WNBA", 15, fetch_props=lambda *_: offers,
        analyze_prop=lambda _: {"confidence": 65, "data_quality": {"score": 80},
                                "hit_rate": {"sample_size": 20}, "forecast_paid_eligible": True},
        end_to_end_eligibility=lambda _: {"eligible": True},
    )
    assert payload["count"] == 15
    assert payload["evaluated_count"] == 17
    assert len({row["player"] for row in payload["props"]}) == 15


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

from analytics.edgeiq_model import MODEL_VERSION, compose_parlay_response, rank_suggestions


def _suggestion(player: str, confidence: float, edge: float, quality: float, warnings=None):
    return {
        "score": confidence,
        "grade": "B",
        "action": "Consider",
        "leg_count": 3,
        "warnings": warnings or [],
        "entry": {
            "average_confidence": confidence,
            "average_edge": edge,
            "props": [
                {
                    "player": player,
                    "direction": "Over",
                    "stat": "Points",
                    "line": 20.5,
                    "confidence": confidence,
                    "edge": edge,
                    "trending_count": 24000,
                    "data_quality": {"score": quality},
                    "espn": {"hit_rate": 58, "sample_size": 8},
                    "source_signals": [{"source": "final_stats"}],
                },
            ],
        },
    }


def test_local_model_ranks_by_quality_and_risk():
    strong = _suggestion("Paige Bueckers", 62, 2.4, 82)
    weak = _suggestion("Risky Player", 64, 1.0, 38, warnings=["correlated legs"])

    ranked = rank_suggestions([weak, strong])

    assert ranked[0].suggestion["entry"]["props"][0]["player"] == "Paige Bueckers"
    assert ranked[0].score > ranked[1].score


def test_local_model_response_includes_direction_and_model_identity():
    message, pick = compose_parlay_response(
        [_suggestion("A'ja Wilson", 66, 3.0, 85)],
        {"leg_count": 3, "sport_label": "WNBA"},
    )

    assert pick is not None
    assert MODEL_VERSION.startswith("edgeiq-local")
    assert "A'ja Wilson Over Points 20.5" in message
    assert "EdgeIQ Local" in message


def test_local_model_response_separates_individual_props_with_commas():
    suggestion = _suggestion("A'ja Wilson", 66, 3.0, 85)
    suggestion["entry"]["props"].append(
        {
            "player": "Paige Bueckers",
            "direction": "Under",
            "stat": "Assists",
            "line": 6.5,
            "confidence": 61,
            "edge": 2.1,
            "data_quality": {"score": 80},
            "source_signals": [{"source": "final_stats"}],
        }
    )

    message, pick = compose_parlay_response([suggestion], {"leg_count": 2, "sport_label": "WNBA"})

    assert pick is not None
    assert "A'ja Wilson Over Points 20.5, Paige Bueckers Under Assists 6.5" in message
    assert "A'ja Wilson Over Points 20.5 + Paige Bueckers" not in message

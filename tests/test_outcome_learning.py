from analytics.model_feedback import _segment_prop_sample
from analytics.outcome_learning import outcome_comparison, verified_settled_entries


def _prop(result="Win", source="espn", **overrides):
    return {
        "player": "Test Player",
        "sport": "WNBA",
        "stat": "Points",
        "platform": "PrizePicks",
        "direction": "Over",
        "line": 20.5,
        "confidence": 60.0,
        "final_result": result,
        "final_source": source,
        **overrides,
    }


def test_outcome_comparison_excludes_unverified_entries():
    entries = [
        {"id": 1, "status": "Settled", "result": "Win", "props": [_prop()]},
        {
            "id": 2,
            "status": "Settled",
            "result": "Loss",
            "props": [_prop("Loss", "projection_estimate")],
        },
    ]

    payload = outcome_comparison(entries)

    assert payload["summary"]["wins_reviewed"] == 1
    assert payload["summary"]["losses_reviewed"] == 0
    assert payload["summary"]["excluded_unverified"] == 1
    assert [entry["id"] for entry in verified_settled_entries(entries)] == [1]


def test_feedback_segment_ignores_projection_estimates():
    entries = [{
        "status": "Settled",
        "props": [
            _prop(player=f"Player {index}", final_source="espn" if index < 20 else "projection_estimate")
            for index in range(25)
        ],
    }]

    class Player:
        sport = "WNBA"

    class Candidate:
        player = Player()
        stat = "Points"
        platform = "PrizePicks"
        direction = "Over"

    sample = _segment_prop_sample(entries, Candidate(), 60)

    assert len(sample) == 20

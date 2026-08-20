import pytest

from web.schemas.entries import EntryPayload


def test_prizepicks_demon_under_is_rejected_with_clear_message() -> None:
    with pytest.raises(ValueError, match="PrizePicks Demon line, which only supports Over"):
        EntryPayload.model_validate({
            "platform": "PrizePicks",
            "props": [{
                "player": "Demon Player",
                "sport": "WNBA",
                "stat": "Points",
                "line": 29.5,
                "direction": "Under",
                "platform": "PrizePicks",
                "line_offer_type": "demon",
                "is_premium_line": True,
            }],
        })


def test_prizepicks_demon_over_is_valid() -> None:
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "props": [{
            "player": "Demon Player",
            "sport": "WNBA",
            "stat": "Points",
            "line": 29.5,
            "direction": "Over",
            "platform": "PrizePicks",
            "line_offer_type": "demon",
            "is_premium_line": True,
        }],
    })

    assert payload.props[0].direction == "Over"


def test_draftkings_pick6_is_detected_from_leg_source() -> None:
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "props": [{
            "player": "Pick6 Player",
            "sport": "NFL",
            "stat": "Receiving Yards",
            "line": 44.5,
            "direction": "Over",
            "platform": "DraftKings Pick6",
        }],
    })

    assert payload.platform == "DraftKings Pick6"
    assert payload.props[0].platform == "DraftKings Pick6"

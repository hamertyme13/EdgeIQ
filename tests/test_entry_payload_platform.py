import pytest
from pydantic import ValidationError

from web.schemas import EntryPayload


def _prop(platform=None):
    row = {
        "player": "Test Player",
        "sport": "WNBA",
        "stat": "Points",
        "line": 20.5,
    }
    if platform is not None:
        row["platform"] = platform
    return row


def test_entry_payload_detects_explicit_prop_platform():
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "props": [_prop("PrizePicks"), _prop("Prize Picks")],
    })

    assert payload.platform == "PrizePicks"


def test_entry_payload_applies_entry_platform_when_prop_platform_is_omitted():
    payload = EntryPayload.model_validate({
        "platform": "Underdog",
        "props": [_prop()],
    })

    assert payload.platform == "Underdog"
    assert payload.props[0].platform == "Underdog"


def test_entry_payload_rejects_mixed_sportsbooks():
    with pytest.raises(ValidationError, match="multiple sportsbooks"):
        EntryPayload.model_validate({
            "platform": "PrizePicks",
            "props": [_prop("PrizePicks"), _prop("Underdog")],
        })


def test_entry_payload_allows_eight_underdog_legs():
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks",
        "props": [
            {**_prop("Underdog"), "player": f"Player {index}"}
            for index in range(8)
        ],
    })

    assert payload.platform == "Underdog"
    assert len(payload.props) == 8


def test_entry_payload_rejects_seven_prizepicks_legs():
    with pytest.raises(ValidationError, match="PrizePicks entries support at most 6 legs"):
        EntryPayload.model_validate({
            "platform": "PrizePicks",
            "props": [
                {**_prop("PrizePicks"), "player": f"Player {index}"}
                for index in range(7)
            ],
        })

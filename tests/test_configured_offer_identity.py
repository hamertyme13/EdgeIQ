import json

import pytest

from data.providers.generic_props import fetch_configured_props, normalize_props


@pytest.mark.parametrize("value, expected", [
    (["Over"], ["Over"]), (["under", "UNDER"], ["Under"]),
    ('["More", "Less"]', ["Over", "Under"]),
    ("Over, Under", ["Over", "Under"]),
    (None, []), ([], []), ("", []), ({"Over": True}, []),
    (["Over", "invalid"], []),
])
def test_explicit_direction_restrictions_survive_normalization(value, expected):
    source = {"player": "Example", "stat": "Points", "line": 10.5,
              "allowed_directions": value}
    row = normalize_props([source], "Sleeper")[0]
    assert row["allowed_directions"] == expected


def test_absent_direction_restrictions_remain_unspecified():
    row = normalize_props([{"player": "Example", "stat": "Points", "line": 10.5}], "Sleeper")[0]
    assert "allowed_directions" not in row


def test_csv_direction_restriction():
    rows = normalize_props('player,stat,line,allowed_directions\nExample,Points,10.5,Under', "Sleeper")
    assert rows[0]["allowed_directions"] == ["Under"]


def test_configured_offer_preserves_explicit_identity():
    row = normalize_props([{"player": "Example", "stat": "Points", "line": 10.5,
                            "offer_id": "offer-1", "event_id": "event-2",
                            "player_id": "player-3", "offer_type": "alternate"}], "Sleeper")[0]
    assert row["provider_offer_id"] == "offer-1"
    assert row["provider_event_id"] == "event-2"
    assert row["provider_player_id"] == "player-3"
    assert row["line_offer_type"] == "alternate"


def test_local_file_does_not_claim_provider_verification(tmp_path, monkeypatch):
    path = tmp_path / "props.json"
    path.write_text(json.dumps([{"player": "Example", "stat": "Points", "line": 10.5,
                                 "provider_offer_verified_at": "2026-09-23T12:00:00Z"}]))
    monkeypatch.delenv("EDGEIQ_SLEEPER_PROPS_URL", raising=False)
    monkeypatch.setenv("EDGEIQ_SLEEPER_PROPS_FILE", str(path))
    row = fetch_configured_props("Sleeper", "SLEEPER")[0]
    assert row["projection_id"] == "sleeper-0"
    assert row["provider_offer_id"] == ""
    assert row["provider_event_id"] == ""
    assert row["provider_offer_verified_at"] == ""
    assert row["offer_evidence_source"] == "Local file"
    assert row["line_offer_type"] == "unknown"

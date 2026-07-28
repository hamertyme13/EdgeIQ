import json
from datetime import date
from pathlib import Path

from data.providers import espn
from data.providers import prizepicks, underdog
from types import SimpleNamespace


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_espn_mlb_final_fixture_preserves_identity_and_scoring() -> None:
    summary = json.loads((FIXTURE_DIR / "espn_mlb_final.json").read_text(encoding="utf-8"))

    rows = espn._parse_summary(summary, "MLB", date(2026, 7, 18))

    points = next(row for row in rows if row["player"] == "Tarik Skubal" and row["stat"] == "Points")
    hits = next(row for row in rows if row["player"] == "Test Hitter" and row["stat"] == "Hits")
    assert points["actual"] == 58
    assert points["provider_player_id"] == "102"
    assert hits["actual"] == 2
    assert hits["provider_player_id"] == "101"


def test_prizepicks_fixture_preserves_offer_and_pra(monkeypatch) -> None:
    payload = json.loads((FIXTURE_DIR / "prizepicks_projection.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        prizepicks,
        "get_json",
        lambda *args, **kwargs: SimpleNamespace(data=payload, stale=False, age_seconds=0),
    )

    row = prizepicks.fetch_projections()[0]

    assert row["player"] == "Azurá Stevens"
    assert row["player_id"] == "p1"
    assert row["stat"] == "Points + Rebounds + Assists"
    assert row["odds_type"] == "goblin"
    assert row["adjusted_odds"] is True
    assert row["game_time"] == "2026-07-25T19:00:00Z"


def test_underdog_fixture_preserves_line_identity_and_game(monkeypatch) -> None:
    payload = json.loads((FIXTURE_DIR / "underdog_projection.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        underdog,
        "get_json",
        lambda *args, **kwargs: SimpleNamespace(data=payload, stale=False, age_seconds=0),
    )

    row = underdog.fetch_projections()[0]

    assert row["player"] == "A'ja Wilson"
    assert row["player_id"] == "2"
    assert row["line"] == 22.5
    assert row["game"] == "LVA @ PHX"
    assert row["game_time"] == "2026-07-25T21:00:00Z"
    assert row["team"] == "LVA"
    assert row["match_id"] == "22"

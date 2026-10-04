from __future__ import annotations

import json

from fastapi.testclient import TestClient

from web.app import app
from web.application.evidence_lab import summarize_evidence_lab


def forecast(key: str, *, outcome: str = "Win", snapshot: dict | None = None, **changes) -> dict:
    row = {
        "independent_market_key": key, "player_identity_id": 1, "model_version": "v2.4",
        "platform": "PrizePicks", "sport": "WNBA", "stat": "Points", "direction": "Over",
        "line": 20.5, "actual": 22 if outcome == "Win" else 18, "probability": 60,
        "outcome": outcome, "outcome_source": "espn", "predicted_at": "2026-09-01T10:00:00Z",
        "feature_as_of": "2026-09-01T09:00:00Z", "game_time": "2026-09-01T18:00:00Z",
        "settled_at": "2026-09-01T22:00:00Z",
        "feature_snapshot": json.dumps(snapshot if snapshot is not None else {"features": {}}),
    }
    return {**row, **changes}


def test_evidence_lab_counts_independent_verified_pregame_outcomes_only():
    context = {"features": {"recent_5_mean": 22.1, "opponent_sample": 4, "opponent_mean": 24},
               "evidence_signals": [{"kind": "weather", "source": "OpenWeather"}]}
    rows = [
        forecast("one", snapshot=context),
        forecast("one", outcome="Loss", predicted_at="2026-09-01T11:00:00Z"),
        forecast("two", outcome="Loss"),
        forecast("late", feature_as_of="2026-09-01T20:00:00Z"),
        forecast("bad-result", outcome="Win", actual=18),
        forecast("unverified", outcome_source="projection_estimate"),
        forecast("missing-snapshot", feature_snapshot=""),
    ]
    result = summarize_evidence_lab(rows)
    recent = next(item for item in result["categories"] if item["key"] == "recent_form")
    opponent = next(item for item in result["categories"] if item["key"] == "opponent_context")
    weather = next(item for item in result["categories"] if item["key"] == "weather")
    assert result["independent_outcomes"] == 2
    assert recent["included"] == {"samples": 1, "wins": 1, "hit_rate": 100.0, "brier": 0.16}
    assert recent["not_included"]["hit_rate"] == 0.0
    assert opponent["included"]["samples"] == 1
    assert weather["included"]["samples"] == 1
    assert recent["descriptive_only"] is True and recent["small_sample"] is True
    assert result["ablation"]["available"] is False


def test_evidence_lab_never_treats_missing_context_as_verified():
    rows = [forecast("one", snapshot={"features": {"opponent_sample": "unavailable", "home_away": "unknown", "workload_evidence": "missing"}})]
    categories = {item["key"]: item for item in summarize_evidence_lab(rows)["categories"]}
    assert categories["opponent_context"]["included"]["samples"] == 0
    assert categories["home_away"]["included"]["samples"] == 0


def test_evidence_lab_endpoint_passes_filters(monkeypatch):
    from web.routers import results

    captured = {}

    def fake_service(*args):
        captured["filters"] = args
        return {"independent_outcomes": 0, "categories": []}

    monkeypatch.setattr(results, "evidence_lab", fake_service)
    response = TestClient(app).get("/api/analytics/evidence-lab", params={"sport": "WNBA", "provider": "PrizePicks"})
    assert response.status_code == 200
    assert captured["filters"] == ("WNBA", "PrizePicks", "", "")

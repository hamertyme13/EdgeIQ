from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from services import recommendation_timeline as timeline
from web.app import app


def test_timeline_change_detection_distinguishes_market_and_model():
    before = {"line": 23.5, "projection": 26.1, "confidence": 67, "calibrated_confidence": 64, "grade": "B"}
    after = {**before, "line": 24.5, "projection": 27.0, "confidence": 69, "grade": "C"}
    assert timeline._changes(before, after) == [
        "provider_line_change", "model_projection_change", "confidence_change", "recommendation_grade_change",
    ]
    assert timeline._changes(after, after) == []
    assert timeline._changes(after, {**after, "model_version": "v2.5"}) == ["model_version_change"]
    assert timeline._probability({"calibrated_confidence": 0, "confidence": 90}) == 0


def test_timeline_reads_immutable_snapshot_sequence(monkeypatch):
    def record(index, line):
        evidence = {"line": line, "projection": 26.1, "confidence": 67, "calibrated_confidence": 64, "grade": "B", "model_version": "v2.4"}
        snapshot = SimpleNamespace(
            id=index, snapshot_id=f"snapshot-{index}", player="Test Player", direction="Over",
            evidence=json.dumps(evidence), created_at=datetime(2026, 10, 3, 12, index, tzinfo=UTC),
        )
        offer = SimpleNamespace(snapshot_id=f"offer-{index}", provider="PrizePicks", sport="WNBA", game="A vs B", stat="Points")
        return snapshot, offer

    class Query:
        def join(self, *args):
            return self

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, _limit):
            return self

        def all(self):
            return [record(2, 24.5), record(1, 23.5)]

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def query(self, *args):
            return Query()

    monkeypatch.setattr(timeline.database, "initialize_database", lambda: None)
    monkeypatch.setattr(timeline.database, "SessionLocal", Session)
    result = timeline.recommendation_timeline(player="Test Player", sport="WNBA", stat="Points")
    assert [event["changes"] for event in result["events"]] == [
        ["recommendation_created"], ["provider_line_change"],
    ]
    assert result["events"][1]["previous_snapshot_id"] == "snapshot-1"
    assert result["events"][1]["previous_line"] == 23.5
    assert result["events"][1]["model_probability"] == 67
    assert result["events"][1]["calibrated_probability"] == 64
    assert result["events"][1]["model_version"] == "v2.4"
    assert result["clv"] is None


def test_timeline_endpoint_accepts_market_filters(monkeypatch):
    from web.routers import recommendations

    captured = {}

    def fake_timeline(**kwargs):
        captured.update(kwargs)
        return {"events": [], "summary": "No saved recommendation changes for this market."}

    monkeypatch.setattr(recommendations, "recommendation_timeline", fake_timeline)
    response = TestClient(app).get("/api/recommendations/timeline", params={
        "player": "Test Player", "sport": "WNBA", "stat": "Points", "platform": "PrizePicks",
    })
    assert response.status_code == 200
    assert captured["player"] == "Test Player"
    assert captured["platform"] == "PrizePicks"

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from web.app import app
from web.application.source_health_service import summarize_source_health


def test_source_health_reports_only_measured_rates_and_distinct_coverage():
    now = datetime(2026, 10, 7, 12, tzinfo=UTC)
    providers = [
        {"name": "PrizePicks", "status": "fresh", "api_usage": {"network_successes": 3, "network_failures": 1},
         "source_type": "public_undocumented_endpoint", "settlement_capable": False},
        {"name": "ESPN public", "status": "stale", "api_usage": {}, "settlement_capable": True},
        {"name": "NewsAPI", "status": "configured", "api_usage": {}, "context_only": True},
    ]
    facts = [("PrizePicks", 2, 4, 3), ("ESPN/NewsAPI/OpenWeather", 3, 9, 6), ("espn", 1, 2, 1)]
    audits = [
        ("ESPN official box score", "waiting", 10), ("espn", "verified", 10),
        ("espn", "blocked", 11), ("espn", "verified", 12),
    ]
    predictions = [
        ("PrizePicks", "market-1", "2026-10-05T10:00:00Z", "Win", "espn"),
        ("PrizePicks", "market-1", "2026-10-05T10:00:00Z", "Win", "espn"),
        ("PrizePicks", "market-2", "2026-10-05T10:00:00Z", "", ""),
        ("PrizePicks", "future", "2026-10-07T20:00:00Z", "", ""),
    ]
    result = summarize_source_health(providers, facts, audits, predictions, now=now)
    rows = {row["name"]: row for row in result["sources"]}
    assert rows["PrizePicks"]["availability_percent_this_session"] == 75.0
    assert rows["PrizePicks"]["error_percent_this_session"] == 25.0
    assert rows["PrizePicks"]["settlement_coverage"]["percent"] == 50.0
    assert rows["PrizePicks"]["research_evidence"] == {"facts": 2, "uses": 4, "linked_outcomes": 3}
    assert rows["ESPN public"]["settlement_coverage"] == {
        "eligible": 3, "verified": 2, "scope": "Distinct ledger legs attempted with this final-stat source, last 30 days", "percent": 66.7,
    }
    assert rows["ESPN public"]["availability_percent_this_session"] is None
    assert rows["NewsAPI"]["settlement_coverage"]["percent"] is None
    assert rows["NewsAPI"]["research_evidence"]["facts"] == 0
    assert "do not establish predictive accuracy" in result["note"]


def test_source_health_endpoint_reuses_compact_provider_health(monkeypatch):
    from web.routers import providers

    class Dependencies:
        def data_health(self, compact):
            assert compact is True
            return {"providers": [{"name": "PrizePicks"}]}

    monkeypatch.setattr(providers, "get_deps", lambda: Dependencies())
    monkeypatch.setattr(providers, "source_health_payload", lambda health: {"sources": health["providers"]})
    response = TestClient(app).get("/api/providers/source-health")
    assert response.status_code == 200
    assert response.json()["sources"][0]["name"] == "PrizePicks"

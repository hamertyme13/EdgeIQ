from repository.repositories.research_evidence_repository import ResearchEvidenceRepository
from web.application.research_service import persist_player_research


def test_research_evidence_is_cached_and_citable():
    payload = {
        "player": "Evidence Player",
        "sport": "WNBA",
        "stat": "Points",
        "platform": "PrizePicks",
        "chart": [{
            "game": "AAA @ BBB", "game_date": "2026-08-01", "actual": 24,
            "source": "ESPN",
        }],
        "active_props": [{
            "platform": "PrizePicks", "game": "AAA @ BBB", "line": 19.5,
            "direction": "Over", "confidence": 61,
        }],
        "forecast": {"distribution": {"expected_result": 22.1}},
        "closing_lines": [],
        "recommendation": {"game": "AAA @ BBB"},
    }

    first = persist_player_research(payload)
    second = persist_player_research(payload)

    assert first["research_memory"]["relevant_active_facts"] == 3
    assert len(first["evidence_citations"]) == 3
    assert first["evidence_coverage"]["available"]["game_logs"] is True
    assert first["evidence_coverage"]["live_lineup_confirmed"] is False
    assert all(row["eligible_for_model_weight"] is False for row in first["evidence_reliability"])
    assert {row["id"] for row in first["evidence"]} == {row["id"] for row in second["evidence"]}
    assert all(row["captured_at"] and row["expires_at"] for row in first["evidence_citations"])


def test_settled_outcome_updates_research_usefulness():
    ResearchEvidenceRepository.record_many([{
        "player": "Outcome Player", "sport": "NFL", "stat": "Receiving Yards",
        "platform": "Underdog", "game": "AAA @ BBB", "evidence_type": "provider_market",
        "source_name": "Underdog", "payload": {"line": 55.5}, "ttl_minutes": 60,
    }])

    entry = {
        "id": 91827,
        "props": [{
            "player": "Outcome Player", "sport": "NFL", "stat": "Receiving Yards",
            "game": "AAA @ BBB", "result": "Win",
        }],
    }
    updated = ResearchEvidenceRepository.record_outcome(entry)
    repeated = ResearchEvidenceRepository.record_outcome(entry)
    rows = ResearchEvidenceRepository.relevant("Outcome Player", "Receiving Yards", sport="NFL")

    assert updated == 1
    assert repeated == 0
    assert rows[0]["outcomes"]["wins"] == 1
    assert rows[0]["outcomes"]["usefulness_score"] > 50

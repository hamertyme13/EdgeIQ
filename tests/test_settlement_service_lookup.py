from repository.repositories.entry_repository import EntryRepository
from repository.repositories.research_evidence_repository import ResearchEvidenceRepository
from web.application.settlement_service import settle_entry_payload


def test_manual_settlement_reads_only_affected_entry(monkeypatch):
    def fail_full_scan():
        raise AssertionError("Manual settlement must not scan the entire ledger")

    monkeypatch.setattr(EntryRepository, "all", fail_full_scan)
    monkeypatch.setattr(
        EntryRepository,
        "settle",
        lambda entry_id, result, dnp_legs, dnp_mode: {"id": entry_id, "result": "Push"},
    )
    monkeypatch.setattr(EntryRepository, "get_by_id", lambda entry_id: {"id": entry_id, "result": "Push"})
    monkeypatch.setattr(ResearchEvidenceRepository, "record_outcome", lambda entry: 1)

    payload = settle_entry_payload(42, "Win", 1, "reduce", lambda: {"record": "updated"})

    assert payload == {
        "id": 42,
        "result": "Push",
        "status": "Settled",
        "research_evidence_updated": 1,
        "research_evidence_warning": "",
        "dashboard": {"record": "updated"},
    }


def test_settlement_remains_successful_when_research_attribution_fails(monkeypatch):
    monkeypatch.setattr(
        EntryRepository,
        "settle",
        lambda entry_id, result, dnp_legs, dnp_mode: {"id": entry_id, "result": "Win"},
    )
    monkeypatch.setattr(EntryRepository, "get_by_id", lambda entry_id: {"id": entry_id, "result": "Win"})

    def fail_attribution(_entry):
        raise RuntimeError("database busy")

    monkeypatch.setattr(ResearchEvidenceRepository, "record_outcome", fail_attribution)
    payload = settle_entry_payload(42, "Win", 0, "reduce", lambda: {})

    assert payload["result"] == "Win"
    assert payload["status"] == "Settled"
    assert payload["research_evidence_updated"] == 0
    assert "Entry settled" in payload["research_evidence_warning"]

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.settlement_audit_repository as audit_module
from repository.database import Base
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.repositories.settlement_audit_repository import SettlementAuditRepository


def test_settlement_audit_deduplicates_retries(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(audit_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(audit_module, "initialize_database", lambda: None)
    payload = {
        "entry_id": 7,
        "entry_prop_id": 19,
        "status": "waiting",
        "provider": "ESPN",
        "requested_player": "Azura Stevens",
        "reason_code": "final_not_available",
        "message": "Waiting for a verified final box score.",
    }

    SettlementAuditRepository.record(payload)
    SettlementAuditRepository.record(payload)
    queue = SettlementAuditRepository.queue()

    assert queue["count"] == 1
    assert queue["waiting"] == 1
    assert queue["items"][0]["attempt_count"] == 2

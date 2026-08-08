from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.settlement_audit_repository as audit_module
from repository.database import Base
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.repositories.settlement_audit_repository import (
    SettlementAuditRepository,
    _game_time_date,
)


def test_game_time_date_uses_eastern_calendar_day():
    assert str(_game_time_date("2026-07-17T02:00:00Z")) == "2026-07-16"


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
    assert queue["scheduled"] == 0
    assert queue["items"][0]["attempt_count"] == 2


def test_settlement_audit_separates_historical_blocks_from_current_queue(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(audit_module, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_module, "initialize_database", lambda: None)
    with session_factory() as session:
        session.add(EntryModel(
            id=7,
            platform="PrizePicks",
            average_confidence=50.0,
            average_edge=0.0,
            wager=0.0,
            multiplier=1.0,
            status="Settled",
            result="Loss",
        ))
        session.commit()

    SettlementAuditRepository.record({
        "entry_id": 7,
        "entry_prop_id": 19,
        "status": "blocked",
        "provider": "ESPN",
        "requested_player": "Legacy Player",
        "reason_code": "legacy_unavailable",
        "message": "Historical result was unavailable.",
    })

    queue = SettlementAuditRepository.queue()

    assert queue["blocked"] == 0
    assert queue["historical_review"] == 1
    assert queue["items"][0]["scope"] == "historical"
    assert queue["items"][0]["entry_status"] == "Settled"

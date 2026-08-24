from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.settlement_audit_repository as audit_module
from repository.database import Base
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.models.final_player_stat_model import FinalPlayerStatModel
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
    assert queue["items"][0]["match_confidence"] == 0
    assert queue["items"][0]["next_retry_at"]
    assert queue["items"][0]["blocking_reason"] == "Waiting for a verified final box score."
    assert queue["items"][0]["retry_state"]["active"] is True
    assert queue["items"][0]["resolution_action"]["code"] == "review"


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
    assert queue["items"][0]["next_retry_at"] == ""
    assert queue["items"][0]["retry_state"]["stopped"] is True


def test_settlement_audit_explains_provider_plan_and_match_checks(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(audit_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(audit_module, "initialize_database", lambda: None)
    SettlementAuditRepository.record({
        "entry_id": 8,
        "entry_prop_id": 21,
        "status": "waiting",
        "provider": "ESPN official box score",
        "matched_identity_id": 91,
        "requested_player": "Azura Stevens",
        "matched_player": "Azurá Stevens",
        "requested_game": "LVA @ LAS",
        "matched_game": "LVA @ LAS",
        "reason_code": "official_final_not_available",
        "message": "Waiting for a verified final box score.",
        "details": {"provider_plan": ["ESPN official box score", "SportsDataIO cross-check"]},
    })

    item = SettlementAuditRepository.queue()["items"][0]

    assert item["match_checks"]["identity"]["status"] == "matched"
    assert item["match_checks"]["game"]["status"] == "matched"
    assert item["match_checks"]["stat"]["status"] == "missing"
    assert [row["provider"] for row in item["provider_attempts"]] == [
        "ESPN official box score", "SportsDataIO cross-check",
    ]
    assert item["provider_attempts"][1]["attempts"] == 0
    assert item["resolution_action"]["code"] == "retry"


def test_latest_settlement_evidence_includes_matched_final_date(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(audit_module, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_module, "initialize_database", lambda: None)
    with session_factory() as session:
        session.add(FinalPlayerStatModel(
            player="Azurá Stevens",
            sport="WNBA",
            stat="Points",
            game="Aces @ Sparks",
            game_date="2026-08-07",
            actual=18,
            source="ESPN",
        ))
        session.commit()
    SettlementAuditRepository.record({
        "entry_id": 12,
        "entry_prop_id": 31,
        "status": "verified",
        "provider": "ESPN",
        "requested_player": "Azura Stevens",
        "matched_player": "Azurá Stevens",
        "requested_game": "LVA @ LAS",
        "matched_game": "Aces @ Sparks",
        "actual": 18,
        "result": "Win",
        "reason_code": "final_stat_matched",
        "message": "Final result verified from ESPN.",
    })

    evidence = SettlementAuditRepository.latest_by_entry_ids([12])

    assert evidence[12][31]["matched_player"] == "Azurá Stevens"
    assert evidence[12][31]["matched_game_dates"] == ["2026-08-07"]
    assert evidence[12][31]["match_confidence"] == 100

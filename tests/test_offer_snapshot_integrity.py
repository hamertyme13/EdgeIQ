from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.database as database
from repository.database import Base
from repository.repositories.provider_offer_snapshot_repository import ProviderOfferSnapshotRepository
from services.offer_snapshot import evidence_status, offer_fingerprint
from web.application.entry_evidence_validation import validate_entry_evidence
from web.schemas.entries import EntryPayload


def _offer(**changes):
    now = datetime.now(UTC)
    return {
        "player": "Azurá Stevens", "platform": "PrizePicks", "sport": "WNBA",
        "stat": "Points", "line": 18.5, "direction": "Over", "game": "LA @ SEA",
        "game_time": (now + timedelta(hours=2)).isoformat(),
        "provider_offer_id": "offer-1", "provider_event_id": "event-1",
        "provider_player_id": "player-1", "line_offer_type": "standard",
        "allowed_directions": ["Over", "Under"],
        "provider_offer_verified_at": now.isoformat(),
        "offer_evidence_source": "direct_provider",
        **changes,
    }


def _isolated(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'offers.db'}")
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session)
    Base.metadata.create_all(engine)


def test_fingerprint_normalizes_identity_but_changes_when_line_changes():
    first = _offer()
    assert offer_fingerprint(first) == offer_fingerprint({**first, "player": "Azura Stevens"})
    assert offer_fingerprint(first) != offer_fingerprint({**first, "line": 19.5})


def test_snapshot_keeps_terms_immutable_and_refreshes_observation(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    first = _offer()
    saved = ProviderOfferSnapshotRepository.capture_many([first])[0]
    snapshot_id = saved["offer_snapshot_id"]
    later = {**first, "provider_offer_verified_at": (datetime.now(UTC) + timedelta(seconds=10)).isoformat()}
    assert ProviderOfferSnapshotRepository.capture_many([later])[0]["offer_snapshot_id"] == snapshot_id
    changed = ProviderOfferSnapshotRepository.capture_many([{**first, "line": 19.5}])[0]
    assert changed["offer_snapshot_id"] != snapshot_id
    original = ProviderOfferSnapshotRepository.get(snapshot_id)
    assert original["line"] == 18.5
    assert original["last_observed_at"] == later["provider_offer_verified_at"]


def test_entry_validation_rejects_changed_terms_and_duplicate_market(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    row = ProviderOfferSnapshotRepository.capture_many([_offer()])[0]
    payload = EntryPayload.model_validate({"platform": "PrizePicks", "props": [{
        **row, "offer_snapshot_id": row["offer_snapshot_id"],
    }]})
    valid = validate_entry_evidence(payload)
    assert valid["valid"] is True
    assert valid["verified_offer"] is True
    payload.props[0].line = 19.5
    changed = validate_entry_evidence(payload)
    assert changed["valid"] is False
    assert "no longer matches" in changed["invalidations"][0]
    payload.props.append(payload.props[0].model_copy())
    assert any("duplicates" in reason for reason in validate_entry_evidence(payload)["invalidations"])


def test_restricted_or_stale_offer_is_not_verified(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    stale_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    row = ProviderOfferSnapshotRepository.capture_many([_offer(
        allowed_directions=["Over"], provider_offer_verified_at=stale_at,
    )])[0]
    payload = EntryPayload.model_validate({"props": [{**row, "offer_snapshot_id": row["offer_snapshot_id"]}]})
    assert validate_entry_evidence(payload)["verified_offer"] is False
    payload.props[0].direction = "Under"
    assert "direction is not allowed" in " ".join(validate_entry_evidence(payload)["invalidations"])
    assert evidence_status({"provider_offer_observed_at": stale_at}) == "EXPIRED"


def test_collector_timestamp_does_not_claim_direct_verification(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    row = ProviderOfferSnapshotRepository.capture_many([_offer(offer_evidence_source="collector")])[0]
    payload = EntryPayload.model_validate({"props": [row]})
    result = validate_entry_evidence(payload)
    assert result["valid"] is True
    assert result["verified_offer"] is False
    assert "collector snapshot" in " ".join(result["warnings"])

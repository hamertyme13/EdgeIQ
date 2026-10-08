from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.database as database
from repository.database import Base
from repository.models.provider_offer_snapshot_model import ProviderOfferSnapshotModel
from repository.repositories.leg_recommendation_snapshot_repository import LegRecommendationSnapshotRepository
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
    assert offer_fingerprint(first) == offer_fingerprint({key: value for key, value in first.items() if key != "player"} | {"player_name": "Azura Stevens"})
    assert offer_fingerprint(first) == offer_fingerprint({key: value for key, value in first.items() if key != "game_time"} | {"scheduled_start": first["game_time"]})
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


def test_parallel_captures_keep_one_offer_and_monotonic_observations(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    monkeypatch.setattr(database, "initialize_database", lambda: None)
    base = _offer()
    observed = [datetime.now(UTC) - timedelta(seconds=offset) for offset in (20, 5, 15, 10)]
    barrier = Barrier(len(observed))

    def capture(at: datetime) -> str:
        barrier.wait(timeout=5)
        return ProviderOfferSnapshotRepository.capture_many([{
            **base, "provider_offer_verified_at": at.isoformat(),
        }])[0]["offer_snapshot_id"]

    with ThreadPoolExecutor(max_workers=len(observed)) as pool:
        ids = list(pool.map(capture, observed))

    assert len(set(ids)) == 1
    with database.SessionLocal() as session:
        assert session.query(ProviderOfferSnapshotModel).count() == 1
    stored = ProviderOfferSnapshotRepository.get(ids[0])
    assert stored["first_observed_at"] == min(observed).isoformat()
    assert stored["last_observed_at"] == max(observed).isoformat()
    assert stored["expires_at"] == (max(observed) + timedelta(minutes=5)).isoformat()


def test_single_batch_preserves_first_and_last_observation(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    base = _offer()
    first = datetime.now(UTC) - timedelta(minutes=2)
    last = first + timedelta(minutes=1)
    rows = ProviderOfferSnapshotRepository.capture_many([
        {**base, "provider_offer_verified_at": last.isoformat()},
        {**base, "provider_offer_verified_at": first.isoformat()},
    ])
    assert rows[0]["offer_snapshot_id"] == rows[1]["offer_snapshot_id"]
    stored = ProviderOfferSnapshotRepository.get(rows[0]["offer_snapshot_id"])
    assert stored["first_observed_at"] == first.isoformat()
    assert stored["last_observed_at"] == last.isoformat()


def test_newer_collector_observation_cannot_extend_direct_verification(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    base = _offer()
    first = datetime.now(UTC) - timedelta(seconds=30)
    later = first + timedelta(seconds=10)
    direct = ProviderOfferSnapshotRepository.capture_many([{
        **base, "provider_offer_verified_at": first.isoformat(),
    }])[0]
    snapshot_id = direct["offer_snapshot_id"]
    collector = ProviderOfferSnapshotRepository.capture_many([{
        **base, "offer_evidence_source": "collector",
        "provider_offer_verified_at": later.isoformat(),
    }])[0]
    assert collector["offer_snapshot_id"] == snapshot_id
    assert ProviderOfferSnapshotRepository.get(snapshot_id)["source"] == "third_party_collector"
    payload = EntryPayload.model_validate({"props": [direct]})
    assert validate_entry_evidence(payload)["verified_offer"] is False

    latest = later + timedelta(seconds=10)
    ProviderOfferSnapshotRepository.capture_many([{
        **base, "provider_offer_verified_at": latest.isoformat(),
    }])
    restored = ProviderOfferSnapshotRepository.get(snapshot_id)
    assert restored["source"] == "direct_verified"
    assert restored["last_observed_at"] == latest.isoformat()
    assert validate_entry_evidence(payload)["verified_offer"] is True


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


def test_leg_recommendation_is_immutable_and_validated_by_exact_feed(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    row = ProviderOfferSnapshotRepository.capture_many([_offer()])[0]
    row.update(projection=21.0, confidence=61.0, recommendation_snapshot_id="feed-1",
               calibration_presentation={"status": "PARTIAL", "label": "Partial calibration evidence",
                                         "sample_size": 34, "segment_sample_size": 8, "basis": "sport-wide fallback",
                                         "calibrated_probability": 58.0})
    LegRecommendationSnapshotRepository.capture([row], feed_snapshot_id="feed-1", model_version="test-v1")
    first_id = row["leg_recommendation_snapshot_id"]
    assert LegRecommendationSnapshotRepository.get(first_id)["confidence"] == 61.0
    assert LegRecommendationSnapshotRepository.get(first_id)["calibration_context"]["status"] == "PARTIAL"
    assert LegRecommendationSnapshotRepository.get(first_id)["calibrated_confidence"] == 58.0
    repeated = dict(row)
    LegRecommendationSnapshotRepository.capture([repeated, repeated], feed_snapshot_id="feed-1", model_version="test-v1")
    assert repeated["leg_recommendation_snapshot_id"] == first_id
    changed = {**row, "confidence": 64.0}
    LegRecommendationSnapshotRepository.capture([changed], feed_snapshot_id="feed-1", model_version="test-v1")
    assert changed["leg_recommendation_snapshot_id"] != first_id
    assert LegRecommendationSnapshotRepository.get(first_id)["confidence"] == 61.0

    payload = EntryPayload.model_validate({"props": [row]})
    result = validate_entry_evidence(payload)
    assert result["recommendation_verified"] is True
    assert result["legs"][0]["authoritative_recommendation"]["confidence"] == 61.0
    payload.props[0].recommendation_snapshot_id = "wrong-feed"
    assert validate_entry_evidence(payload)["recommendation_verified"] is False


def test_unscored_offer_does_not_become_model_recommendation(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    row = ProviderOfferSnapshotRepository.capture_many([_offer()])[0]
    LegRecommendationSnapshotRepository.capture([row], feed_snapshot_id="feed-1", model_version="test-v1")
    assert "leg_recommendation_snapshot_id" not in row

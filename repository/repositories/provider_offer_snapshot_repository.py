"""Persist stable offer terms separately from their changing observation time."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from repository import database
from repository.models.provider_offer_snapshot_model import ProviderOfferSnapshotModel
from services.offer_snapshot import OFFER_EVIDENCE_TTL, canonical_offer, observation_time, offer_fingerprint


class ProviderOfferSnapshotRepository:
    @staticmethod
    def capture_many(rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        database.initialize_database()
        now = datetime.now(UTC)
        prepared = []
        for row in rows:
            offer = canonical_offer(row)
            snapshot_id = offer_fingerprint(row)
            if offer is None or snapshot_id is None:
                prepared.append({**row, "offer_snapshot_id": "", "offer_snapshot_status": "UNKNOWN"})
                continue
            observed = observation_time(row)
            source_id = str(row.get("source_id") or row.get("collector") or row.get("offer_evidence_source") or "")
            source_kind = (
                "direct_verified"
                if row.get("offer_evidence_source") == "direct_provider" and row.get("provider_offer_verified_at")
                else "third_party_collector" if source_id or row.get("provider_offer_verified_at") else "unknown"
            )
            prepared.append({
                "raw": row, "offer": offer, "snapshot_id": snapshot_id,
                "observed": observed, "source": source_kind,
                "source_hash": hashlib.sha256(source_id.encode()).hexdigest() if source_id else "",
            })
        with database.SessionLocal() as session:
            for item in prepared:
                if "snapshot_id" not in item:
                    continue
                offer = item["offer"]
                seen = item["observed"]
                observed = seen.isoformat() if seen else ""
                expires = (seen + OFFER_EVIDENCE_TTL).isoformat() if seen else ""
                existing = session.query(ProviderOfferSnapshotModel).filter_by(snapshot_id=item["snapshot_id"]).first()
                if existing is None:
                    record = ProviderOfferSnapshotModel(
                        snapshot_id=item["snapshot_id"],
                        **{key: value for key, value in offer.items() if key != "allowed_directions"},
                        allowed_directions=json.dumps(offer["allowed_directions"]),
                        source=item["source"], source_hash=item["source_hash"],
                        first_observed_at=observed, last_observed_at=observed,
                        expires_at=expires, created_at=now.isoformat(),
                    )
                    try:
                        with session.begin_nested():
                            session.add(record)
                            session.flush()
                    except IntegrityError:
                        existing = session.query(ProviderOfferSnapshotModel).filter_by(snapshot_id=item["snapshot_id"]).first()
                if existing is not None and seen and (
                    not existing.last_observed_at or observed > existing.last_observed_at
                ):
                    existing.last_observed_at = observed
                    existing.expires_at = expires
            session.commit()
        result = []
        for item in prepared:
            if "snapshot_id" not in item:
                result.append(item)
            else:
                result.append({**item["raw"], "offer_snapshot_id": item["snapshot_id"]})
        return result

    @staticmethod
    def get(snapshot_id: str) -> dict | None:
        if not snapshot_id:
            return None
        database.initialize_database()
        with database.SessionLocal() as session:
            row = session.query(ProviderOfferSnapshotModel).filter_by(snapshot_id=snapshot_id).first()
            if row is None:
                return None
            return {
                "snapshot_id": row.snapshot_id, "provider": row.provider,
                "provider_offer_id": row.provider_offer_id,
                "provider_player_id": row.provider_player_id,
                "provider_event_id": row.provider_event_id,
                "player_key": row.player_key, "sport": row.sport, "game": row.game,
                "game_start": row.game_start, "stat": row.stat,
                "allowed_directions": json.loads(row.allowed_directions or "[]"),
                "line": row.line, "offer_type": row.offer_type,
                "standard_line": row.standard_line, "baseline_line": row.baseline_line,
                "discounted": row.discounted, "premium": row.premium,
                "source": row.source, "source_hash": row.source_hash,
                "first_observed_at": row.first_observed_at,
                "last_observed_at": row.last_observed_at,
                "expires_at": row.expires_at, "created_at": row.created_at,
            }

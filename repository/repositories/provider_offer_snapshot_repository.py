"""Persist stable offer terms separately from their changing observation time."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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
        unique: dict[str, dict] = {}
        for item in prepared:
            if "snapshot_id" in item:
                group = unique.setdefault(item["snapshot_id"], {
                    **item, "first_seen": item["observed"], "last_seen": item["observed"],
                })
                observed = item["observed"]
                if observed and (group["first_seen"] is None or observed < group["first_seen"]):
                    group["first_seen"] = observed
                if observed and (group["last_seen"] is None or observed > group["last_seen"]):
                    group["last_seen"] = observed
                    group["source"] = item["source"]
                    group["source_hash"] = item["source_hash"]
        with database.SessionLocal() as session:
            if unique:
                inserts = []
                for item in unique.values():
                    offer = item["offer"]
                    first_seen = item["first_seen"]
                    last_seen = item["last_seen"]
                    inserts.append({
                        "snapshot_id": item["snapshot_id"],
                        **{key: value for key, value in offer.items() if key != "allowed_directions"},
                        "allowed_directions": json.dumps(offer["allowed_directions"]),
                        "source": item["source"], "source_hash": item["source_hash"],
                        "first_observed_at": first_seen.isoformat() if first_seen else "",
                        "last_observed_at": last_seen.isoformat() if last_seen else "",
                        "expires_at": (last_seen + OFFER_EVIDENCE_TTL).isoformat() if last_seen else "",
                        "created_at": now.isoformat(),
                    })
                insert_factory = postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
                insert = insert_factory(ProviderOfferSnapshotModel).values(inserts)
                current = ProviderOfferSnapshotModel
                incoming = insert.excluded
                newer = incoming.last_observed_at > current.last_observed_at
                earlier = (current.first_observed_at == "") | (
                    (incoming.first_observed_at != "")
                    & (incoming.first_observed_at < current.first_observed_at)
                )
                session.execute(insert.on_conflict_do_update(
                    index_elements=["snapshot_id"],
                    set_={
                        "first_observed_at": case((earlier, incoming.first_observed_at), else_=current.first_observed_at),
                        "last_observed_at": case((newer, incoming.last_observed_at), else_=current.last_observed_at),
                        "expires_at": case((newer, incoming.expires_at), else_=current.expires_at),
                        "source": case((newer, incoming.source), else_=current.source),
                        "source_hash": case((newer, incoming.source_hash), else_=current.source_hash),
                    },
                ))
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
                "allowed_directions": json.loads(str(row.allowed_directions or "[]")),
                "line": row.line, "offer_type": row.offer_type,
                "standard_line": row.standard_line, "baseline_line": row.baseline_line,
                "discounted": row.discounted, "premium": row.premium,
                "source": row.source, "source_hash": row.source_hash,
                "first_observed_at": row.first_observed_at,
                "last_observed_at": row.last_observed_at,
                "expires_at": row.expires_at, "created_at": row.created_at,
            }

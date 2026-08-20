from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from repository.database import SessionLocal, initialize_database
from repository.models.research_evidence_model import ResearchEvidenceModel
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.time import utc_now


class ResearchEvidenceRepository:
    @staticmethod
    def record_many(facts: list[dict]) -> list[dict]:
        initialize_database()
        now = utc_now().replace(tzinfo=None)
        stored: list[dict] = []
        with SessionLocal() as session:
            for fact in facts:
                payload = fact.get("payload") or {}
                fingerprint = _fingerprint(fact, payload)
                row = session.query(ResearchEvidenceModel).filter_by(fingerprint=fingerprint).one_or_none()
                ttl_minutes = max(1, int(fact.get("ttl_minutes") or 60))
                if row is None:
                    row = ResearchEvidenceModel(
                        evidence_id=f"ev-{uuid.uuid4().hex[:16]}",
                        fingerprint=fingerprint,
                        player_key=canonical_person_key(fact.get("player")),
                        player=str(fact.get("player") or ""),
                        sport=str(fact.get("sport") or "").upper(),
                        stat=str(fact.get("stat") or ""),
                        platform=str(fact.get("platform") or ""),
                        game_key=canonical_matchup_key(fact.get("game")),
                        game=str(fact.get("game") or ""),
                        evidence_type=str(fact.get("evidence_type") or "context"),
                        source_name=str(fact.get("source_name") or "EdgeIQ"),
                        source_url=str(fact.get("source_url") or ""),
                        source_kind=str(fact.get("source_kind") or "api"),
                        captured_at=now,
                        expires_at=now + timedelta(minutes=ttl_minutes),
                        last_accessed_at=now,
                        payload=json.dumps(payload, default=str, sort_keys=True),
                    )
                    try:
                        with session.begin_nested():
                            session.add(row)
                            session.flush()
                    except IntegrityError:
                        row = session.query(ResearchEvidenceModel).filter_by(fingerprint=fingerprint).one()
                        row.last_accessed_at = now
                        if row.expires_at < now:
                            row.expires_at = now + timedelta(minutes=ttl_minutes)
                else:
                    row.last_accessed_at = now
                    if row.expires_at < now:
                        row.expires_at = now + timedelta(minutes=ttl_minutes)
                stored.append(_serialize(row, now))
            session.commit()
        return stored

    @staticmethod
    def relevant(
        player: str,
        stat: str = "",
        *,
        sport: str = "",
        platform: str = "",
        game: str = "",
        include_expired: bool = False,
        limit: int = 80,
    ) -> list[dict]:
        initialize_database()
        now = utc_now().replace(tzinfo=None)
        player_key = canonical_person_key(player)
        with SessionLocal() as session:
            query = session.query(ResearchEvidenceModel).filter_by(player_key=player_key)
            if stat:
                query = query.filter_by(stat=stat)
            if sport:
                query = query.filter_by(sport=sport.upper())
            if platform and platform not in {"Both", "All Platforms"}:
                query = query.filter(
                    ResearchEvidenceModel.platform.in_([platform, "", "Both"])
                )
            if game:
                query = query.filter_by(game_key=canonical_matchup_key(game))
            if not include_expired:
                query = query.filter(ResearchEvidenceModel.expires_at >= now)
            rows = query.order_by(
                ResearchEvidenceModel.captured_at.desc(), ResearchEvidenceModel.id.desc()
            ).limit(max(1, min(limit, 500))).all()
            for row in rows:
                row.last_accessed_at = now
            session.commit()
            return [_serialize(row, now) for row in rows]

    @staticmethod
    def record_outcome(entry: dict) -> int:
        """Attribute a settled leg outcome to evidence available for that exact market."""
        initialize_database()
        updated = 0
        now = utc_now().replace(tzinfo=None)
        with SessionLocal() as session:
            for prop in entry.get("props") or []:
                outcome = str(prop.get("final_result") or prop.get("result") or "").title()
                if outcome not in {"Win", "Loss", "Push", "Dnp"}:
                    continue
                query = session.query(ResearchEvidenceModel).filter_by(
                    player_key=canonical_person_key(prop.get("player")),
                    stat=str(prop.get("stat") or ""),
                    sport=str(prop.get("sport") or "").upper(),
                )
                game_key = canonical_matchup_key(prop.get("game"))
                if game_key:
                    query = query.filter(
                        ResearchEvidenceModel.game_key.in_([game_key, ""])
                    )
                outcome_key = _outcome_key(entry, prop, outcome)
                for row in query.filter(ResearchEvidenceModel.captured_at <= now).all():
                    seen = _json_list(row.outcome_keys)
                    if outcome_key in seen:
                        continue
                    seen.append(outcome_key)
                    row.outcome_keys = json.dumps(seen[-500:])
                    row.use_count += 1
                    if outcome == "Win":
                        row.win_count += 1
                    elif outcome == "Loss":
                        row.loss_count += 1
                    else:
                        row.push_count += 1
                    decisions = row.win_count + row.loss_count
                    row.usefulness_score = round(
                        ((row.win_count + 1.0) / (decisions + 2.0)) * 100.0,
                        2,
                    )
                    updated += 1
            session.commit()
        return updated

    @staticmethod
    def summary() -> dict:
        initialize_database()
        now = utc_now().replace(tzinfo=None)
        with SessionLocal() as session:
            rows = session.query(ResearchEvidenceModel).all()
            return {
                "facts": len(rows),
                "active": sum(row.expires_at >= now for row in rows),
                "expired": sum(row.expires_at < now for row in rows),
                "outcome_linked": sum(row.use_count > 0 for row in rows),
                "sources": sorted({row.source_name for row in rows}),
            }


def _fingerprint(fact: dict, payload: dict) -> str:
    identity = {
        "player": canonical_person_key(fact.get("player")),
        "sport": str(fact.get("sport") or "").upper(),
        "stat": str(fact.get("stat") or ""),
        "platform": str(fact.get("platform") or ""),
        "game": canonical_matchup_key(fact.get("game")),
        "evidence_type": str(fact.get("evidence_type") or "context"),
        "source_name": str(fact.get("source_name") or "EdgeIQ"),
        "payload": payload,
    }
    return hashlib.sha256(json.dumps(identity, default=str, sort_keys=True).encode()).hexdigest()


def _serialize(row: ResearchEvidenceModel, now) -> dict:
    decisions = row.win_count + row.loss_count
    return {
        "id": row.evidence_id,
        "player": row.player,
        "sport": row.sport,
        "stat": row.stat,
        "platform": row.platform,
        "game": row.game,
        "type": row.evidence_type,
        "source": row.source_name,
        "source_url": row.source_url,
        "source_kind": row.source_kind,
        "captured_at": row.captured_at.isoformat() if row.captured_at else "",
        "expires_at": row.expires_at.isoformat() if row.expires_at else "",
        "fresh": bool(row.expires_at and row.expires_at >= now),
        "payload": _json(row.payload),
        "outcomes": {
            "uses": row.use_count,
            "wins": row.win_count,
            "losses": row.loss_count,
            "pushes": row.push_count,
            "decisions": decisions,
            "usefulness_score": row.usefulness_score,
        },
    }


def _json(value: str) -> dict:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _outcome_key(entry: dict, prop: dict, outcome: str) -> str:
    identity = {
        "entry_id": entry.get("id"),
        "player": canonical_person_key(prop.get("player")),
        "sport": str(prop.get("sport") or "").upper(),
        "stat": str(prop.get("stat") or ""),
        "game": canonical_matchup_key(prop.get("game")),
        "line": prop.get("line"),
        "direction": prop.get("direction"),
        "outcome": outcome,
    }
    return hashlib.sha256(json.dumps(identity, default=str, sort_keys=True).encode()).hexdigest()

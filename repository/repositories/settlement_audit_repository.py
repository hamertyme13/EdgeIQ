from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from repository.database import SessionLocal, initialize_database
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.settlement_audit_model import SettlementAuditModel
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.time import utc_now


class SettlementAuditRepository:
    @staticmethod
    def record(payload: dict) -> None:
        initialize_database()
        entry_prop_id = int(payload.get("entry_prop_id") or 0)
        if not entry_prop_id:
            return
        status = str(payload.get("status") or "pending")
        provider = str(payload.get("provider") or "")
        reason_code = str(payload.get("reason_code") or "")
        with SessionLocal() as session:
            row = (
                session.query(SettlementAuditModel)
                .filter_by(
                    entry_prop_id=entry_prop_id,
                    status=status,
                    provider=provider,
                    reason_code=reason_code,
                )
                .first()
            )
            values = {
                "entry_id": int(payload.get("entry_id") or 0),
                "entry_prop_id": entry_prop_id,
                "status": status,
                "provider": provider,
                "matched_identity_id": payload.get("matched_identity_id"),
                "requested_player": str(payload.get("requested_player") or ""),
                "matched_player": str(payload.get("matched_player") or ""),
                "requested_game": str(payload.get("requested_game") or ""),
                "matched_game": str(payload.get("matched_game") or ""),
                "actual": payload.get("actual"),
                "result": str(payload.get("result") or ""),
                "reason_code": reason_code,
                "message": str(payload.get("message") or ""),
                "details": json.dumps(payload.get("details") or {}),
                "attempted_at": utc_now(),
            }
            if row is None:
                session.add(SettlementAuditModel(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.attempt_count = int(row.attempt_count or 0) + 1
            session.commit()

    @staticmethod
    def queue(limit: int = 100) -> dict:
        initialize_database()
        with SessionLocal() as session:
            rows = (
                session.query(SettlementAuditModel)
                .order_by(SettlementAuditModel.attempted_at.desc(), SettlementAuditModel.id.desc())
                .all()
            )
            latest: dict[int, SettlementAuditModel] = {}
            for row in rows:
                latest.setdefault(row.entry_prop_id, row)
            entry_ids = {row.entry_id for row in latest.values()}
            entry_statuses = {
                row.id: row.status
                for row in session.query(EntryModel.id, EntryModel.status)
                .filter(EntryModel.id.in_(entry_ids))
                .all()
            }
            all_items = []
            for row in latest.values():
                item = _serialize(row)
                entry_status = str(entry_statuses.get(row.entry_id) or "")
                item["entry_status"] = entry_status
                item["scope"] = "current" if entry_status in {"", "Pending"} else "historical"
                all_items.append(item)
            all_items.sort(
                key=lambda item: (
                    item["scope"] != "current",
                    item["status"] == "verified",
                )
            )
            items = all_items[:max(1, min(limit, 500))]
        counts: dict[str, int] = {}
        current_items = [item for item in all_items if item["scope"] == "current"]
        for item in current_items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        historical_review = sum(
            1
            for item in all_items
            if item["scope"] == "historical" and item["status"] in {"blocked", "waiting"}
        )
        return {
            "items": items,
            "count": len(items),
            "verified": sum(1 for item in all_items if item["status"] == "verified"),
            "scheduled": counts.get("scheduled", 0),
            "waiting": counts.get("waiting", 0),
            "blocked": counts.get("blocked", 0),
            "historical_review": historical_review,
            "statuses": counts,
        }

    @staticmethod
    def latest_by_entry_ids(entry_ids: list[int]) -> dict[int, dict[int, dict]]:
        """Return the latest audit evidence for each requested entry leg."""
        ids = {int(entry_id) for entry_id in entry_ids if int(entry_id or 0) > 0}
        if not ids:
            return {}
        initialize_database()
        with SessionLocal() as session:
            rows = (
                session.query(SettlementAuditModel)
                .filter(SettlementAuditModel.entry_id.in_(ids))
                .order_by(SettlementAuditModel.attempted_at.desc(), SettlementAuditModel.id.desc())
                .all()
            )
            latest: dict[int, SettlementAuditModel] = {}
            for row in rows:
                latest.setdefault(row.entry_prop_id, row)
            matched_players = {row.matched_player for row in latest.values() if row.matched_player}
            matched_games = {row.matched_game for row in latest.values() if row.matched_game}
            matched_sources = {row.provider for row in latest.values() if row.provider}
            final_query = session.query(
                FinalPlayerStatModel.player,
                FinalPlayerStatModel.game,
                FinalPlayerStatModel.source,
                FinalPlayerStatModel.actual,
                FinalPlayerStatModel.game_date,
            )
            if matched_players:
                final_query = final_query.filter(FinalPlayerStatModel.player.in_(matched_players))
            if matched_games:
                final_query = final_query.filter(FinalPlayerStatModel.game.in_(matched_games))
            if matched_sources:
                final_query = final_query.filter(FinalPlayerStatModel.source.in_(matched_sources))
            final_rows = final_query.all() if matched_players and matched_games else []

        dates_by_evidence: dict[tuple, set[str]] = {}
        for row in final_rows:
            key = _final_evidence_key(row.player, row.game, row.source, row.actual)
            if row.game_date:
                dates_by_evidence.setdefault(key, set()).add(str(row.game_date))

        result: dict[int, dict[int, dict]] = {}
        for row in latest.values():
            item = _serialize(row)
            key = _final_evidence_key(row.matched_player, row.matched_game, row.provider, row.actual)
            item["matched_game_dates"] = sorted(dates_by_evidence.get(key, set()))
            result.setdefault(row.entry_id, {})[row.entry_prop_id] = item
        return result

    @staticmethod
    def game_date_mismatches(max_day_delta: int = 1) -> list[dict]:
        """Find verified legs whose stored start date conflicts with matched evidence."""
        initialize_database()
        with SessionLocal() as session:
            audits = (
                session.query(SettlementAuditModel)
                .filter(SettlementAuditModel.status == "verified")
                .order_by(SettlementAuditModel.attempted_at.desc(), SettlementAuditModel.id.desc())
                .all()
            )
            latest: dict[int, SettlementAuditModel] = {}
            for audit in audits:
                latest.setdefault(audit.entry_prop_id, audit)
            props = {
                row.id: row
                for row in session.query(EntryPropModel)
                .filter(EntryPropModel.id.in_(latest))
                .all()
            }
            stat_dates: dict[tuple, set[str]] = {}
            for row in session.query(
                FinalPlayerStatModel.player,
                FinalPlayerStatModel.game,
                FinalPlayerStatModel.source,
                FinalPlayerStatModel.actual,
                FinalPlayerStatModel.game_date,
            ).all():
                key = _final_evidence_key(row.player, row.game, row.source, row.actual)
                stat_dates.setdefault(key, set()).add(str(row.game_date or ""))

        mismatches = []
        for prop_id, audit in latest.items():
            prop = props.get(prop_id)
            stored_date = _game_time_date(getattr(prop, "game_time", ""))
            if stored_date is None:
                continue
            key = _final_evidence_key(
                audit.matched_player,
                audit.matched_game,
                audit.provider,
                audit.actual,
            )
            evidence_dates = {
                parsed
                for parsed in (_date_value(value) for value in stat_dates.get(key, set()))
                if parsed is not None
            }
            if not evidence_dates or any(
                abs((stored_date - evidence_date).days) <= max_day_delta
                for evidence_date in evidence_dates
            ):
                continue
            mismatches.append({
                "entry_id": audit.entry_id,
                "entry_prop_id": prop_id,
                "player": audit.requested_player,
                "requested_game": audit.requested_game,
                "matched_game": audit.matched_game,
                "stored_game_date": stored_date.isoformat(),
                "evidence_game_dates": sorted(value.isoformat() for value in evidence_dates),
                "provider": audit.provider,
            })
        return mismatches


def _serialize(row: SettlementAuditModel) -> dict:
    try:
        details = json.loads(row.details or "{}")
    except (TypeError, ValueError):
        details = {}
    return {
        "id": row.id,
        "entry_id": row.entry_id,
        "entry_prop_id": row.entry_prop_id,
        "status": row.status,
        "provider": row.provider,
        "matched_identity_id": row.matched_identity_id,
        "requested_player": row.requested_player,
        "matched_player": row.matched_player,
        "requested_game": row.requested_game,
        "matched_game": row.matched_game,
        "actual": row.actual,
        "result": row.result,
        "reason_code": row.reason_code,
        "message": row.message,
        "attempt_count": row.attempt_count,
        "attempted_at": row.attempted_at.isoformat() if row.attempted_at else "",
        "details": details,
    }


def _final_evidence_key(player: object, game: object, provider: object, actual: object) -> tuple:
    try:
        actual_key = round(float(actual), 6)
    except (TypeError, ValueError):
        actual_key = None
    return (
        canonical_person_key(player),
        canonical_matchup_key(game),
        str(provider or "").strip().lower(),
        actual_key,
    )


def _date_value(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _game_time_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _date_value(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo("America/New_York"))
    return parsed.date()

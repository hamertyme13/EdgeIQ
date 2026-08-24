from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

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
            try:
                session.commit()
            except IntegrityError:
                # A manual action and scheduler retry can observe the row as
                # missing simultaneously. Preserve one audit row and count both attempts.
                session.rollback()
                row = (
                    session.query(SettlementAuditModel)
                    .filter_by(
                        entry_prop_id=entry_prop_id,
                        status=status,
                        provider=provider,
                        reason_code=reason_code,
                    )
                    .one()
                )
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
            history: dict[int, list[SettlementAuditModel]] = {}
            for row in rows:
                latest.setdefault(row.entry_prop_id, row)
                history.setdefault(row.entry_prop_id, []).append(row)
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
                item["provider_attempts"] = _provider_attempts(history.get(row.entry_prop_id, []))
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
    confidence = _match_confidence(row)
    next_retry = None
    retryable = row.status in {"scheduled", "waiting"}
    if row.status == "scheduled":
        game_time = _datetime_value(details.get("game_time"))
        if game_time is not None:
            delays = {"NBA": 3.25, "WNBA": 3.25, "NFL": 4.0, "MLB": 4.5, "NHL": 3.0}
            next_retry = game_time + timedelta(hours=delays.get(str(details.get("sport") or "").upper(), 4.0))
    elif retryable and row.attempted_at:
        attempted = row.attempted_at.replace(tzinfo=UTC) if row.attempted_at.tzinfo is None else row.attempted_at
        delay_minutes = min(360, 15 * (2 ** max(0, int(row.attempt_count or 1) - 1)))
        next_retry = attempted + timedelta(minutes=delay_minutes)
    current = utc_now()
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
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
        "match_confidence": confidence,
        "next_retry_at": next_retry.isoformat() if next_retry else "",
        "retry_state": {
            "active": retryable,
            "stopped": row.status == "blocked",
            "due": bool(next_retry and next_retry <= current),
            "label": (
                "Waiting for confirmed game time" if row.status == "scheduled" and next_retry is None
                else "Automatic retry scheduled" if retryable
                else "Verified" if row.status == "verified"
                else "Automatic retries stopped"
            ),
        },
        "blocking_reason": _blocking_reason(row.reason_code, row.message),
        "match_checks": _match_checks(row),
        "resolution_action": _resolution_action(row),
        "details": details,
    }


def _match_confidence(row: SettlementAuditModel) -> int:
    if row.status == "verified":
        return 100
    score = 0
    if row.matched_identity_id:
        score += 45
    if canonical_person_key(row.requested_player) == canonical_person_key(row.matched_player) and row.matched_player:
        score += 30
    if canonical_matchup_key(row.requested_game) == canonical_matchup_key(row.matched_game) and row.matched_game:
        score += 25
    return score


def _blocking_reason(reason_code: str, message: str) -> str:
    labels = {
        "game_not_final": "The game has not been confirmed final yet.",
        "player_not_found": "The final-stat provider did not return a matching player.",
        "game_mismatch": "The saved matchup does not match the provider's final game.",
        "stat_unavailable": "The provider final does not contain this stat market.",
        "provider_unavailable": "The final-stat provider is temporarily unavailable.",
        "game_not_started": "The game has not started; no final result should exist yet.",
        "official_final_not_available": "The official box score is not final or does not contain a matching player and stat yet.",
        "official_final_retry_window_expired": "The automatic retry window ended without verified player-stat evidence.",
        "unsupported_settlement_path": "This market does not have a verified automatic settlement source.",
    }
    return labels.get(str(reason_code or "").lower(), str(message or "Waiting for verified final data."))


def _match_checks(row: SettlementAuditModel) -> dict:
    if row.status == "scheduled":
        return {
            "identity": {"status": "pending", "label": "Player check begins after game"},
            "game": {"status": "pending", "label": "Game check begins after game"},
            "stat": {"status": "pending", "label": "Final stat not expected yet"},
        }
    player_exact = bool(
        row.matched_player
        and canonical_person_key(row.requested_player) == canonical_person_key(row.matched_player)
    )
    game_exact = bool(
        row.matched_game
        and canonical_matchup_key(row.requested_game) == canonical_matchup_key(row.matched_game)
    )
    return {
        "identity": {
            "status": "matched" if row.matched_identity_id or player_exact else "missing",
            "label": "Player identity matched" if row.matched_identity_id or player_exact else "Player identity not matched",
        },
        "game": {
            "status": "matched" if game_exact else "partial" if row.matched_game else "missing",
            "label": "Exact game matched" if game_exact else "Different game candidate found" if row.matched_game else "Game not matched",
        },
        "stat": {
            "status": "matched" if row.actual is not None or row.status == "verified" else "missing",
            "label": "Final stat verified" if row.actual is not None or row.status == "verified" else "Final stat unavailable",
        },
    }


def _resolution_action(row: SettlementAuditModel) -> dict:
    reason = str(row.reason_code or "").lower()
    if row.status == "verified":
        return {"code": "none", "label": "No action needed", "description": "This leg has verified final evidence."}
    if reason == "game_not_started":
        return {"code": "wait", "label": "Wait for the game", "description": "EdgeIQ will begin checking after the expected completion window."}
    if reason == "official_final_not_available":
        return {"code": "retry", "label": "Retry automatically", "description": "No manual action is needed unless the retry window expires."}
    if reason == "official_final_retry_window_expired":
        return {"code": "recheck", "label": "Recheck final stats", "description": "Run a fresh provider check, then review the player and matchup if it remains blocked."}
    if reason == "unsupported_settlement_path":
        return {"code": "import", "label": "Import a verified result", "description": "Connect a supported results feed or import provider-backed final evidence."}
    return {"code": "review", "label": "Review leg details", "description": "Confirm the player, matchup, game time, stat, and provider."}


def _provider_attempts(rows: list[SettlementAuditModel]) -> list[dict]:
    attempts: dict[str, dict] = {}
    planned: list[str] = []
    for row in rows:
        try:
            details = json.loads(row.details or "{}")
        except (TypeError, ValueError):
            details = {}
        for provider in details.get("provider_plan") or []:
            label = _provider_label(provider)
            if label and label not in planned:
                planned.append(label)
        provider = _provider_label(row.provider)
        current = attempts.setdefault(provider, {
            "provider": provider,
            "attempts": 0,
            "last_status": "not_tried",
            "last_attempt_at": "",
            "message": "No attempt recorded yet.",
        })
        provider_calls = 0 if row.status == "scheduled" else int(row.attempt_count or 1)
        current.update({
            "attempts": int(current["attempts"]) + provider_calls,
            "last_status": row.status,
            "last_attempt_at": row.attempted_at.isoformat() if row.attempted_at else "",
            "message": row.message,
        })
    for provider in planned:
        attempts.setdefault(provider, {
            "provider": provider,
            "attempts": 0,
            "last_status": "not_tried",
            "last_attempt_at": "",
            "message": "Available as a settlement source; no distinct attempt was recorded.",
        })
    return list(attempts.values())


def _provider_label(value: object) -> str:
    label = str(value or "Provider pending").strip()
    aliases = {
        "espn": "ESPN official box score",
        "espn_final_stats": "ESPN official box score",
        "espn_live": "ESPN official box score",
        "sportsdataio": "SportsDataIO cross-check",
        "pandascore_verified": "PandaScore",
    }
    return aliases.get(label.lower(), label)


def _final_evidence_key(player: object, game: object, provider: object, actual: object) -> tuple:
    try:
        actual_key = round(float(str(actual)), 6)
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


def _datetime_value(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


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

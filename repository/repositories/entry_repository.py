import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from repository.database import SessionLocal, initialize_database
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from utils.time import utc_now

from models.entry import Entry
from analytics.entry_recommendation import recommendation as entry_recommendation


class EntryRepository:
    _schema_ready = False
    DEFAULT_WAGER = 10.0
    DEFAULT_MULTIPLIERS = {
        2: 3.0,
        3: 5.0,
        4: 10.0,
        5: 20.0,
        6: 37.5,
    }
    TEAM_ALIASES = {
        "LAS": "LV",
        "LVA": "LV",
        "NYL": "NY",
        "PHO": "PHX",
        "GSV": "GS",
    }

    @staticmethod
    def _ensure_schema() -> None:
        if EntryRepository._schema_ready:
            return
        initialize_database()
        EntryRepository._schema_ready = True

    @staticmethod
    def save(
        entry: Entry,
        status: str = "Draft",
        result: str = "",
        wager: float = 0.0,
        multiplier: float = 1.0,
        recommended_by_app: bool = False,
        audit_snapshot: str = "",
        entry_mode: str = "real",
    ) -> int:

        EntryRepository._ensure_schema()
        session: Session = SessionLocal()

        try:
            analysis = entry_recommendation(entry)
            wager = round(float(wager or 0), 2)
            multiplier = round(float(multiplier or 1), 2)
            potential_payout = round(wager * multiplier, 2)
            entry_mode = EntryRepository._normalize_entry_mode(entry_mode)

            entry_model = EntryModel(
                platform=entry.platform.value,
                average_confidence=entry.average_confidence,
                average_edge=entry.average_edge,
                grade=analysis["grade"],
                recommendation=analysis["action"],
                wager=wager,
                multiplier=multiplier,
                potential_payout=potential_payout,
                profit=EntryRepository._profit_for_result(result, wager, multiplier),
                status=status,
                result=result,
                entry_mode=entry_mode,
                recommended_by_app=bool(recommended_by_app),
                audit_snapshot=audit_snapshot or "",
                placed_at=utc_now() if status == "Pending" else None,
            )

            session.add(entry_model)
            session.flush()

            for prop in entry.props:

                prop_model = EntryPropModel(
                    entry_id=entry_model.id,
                    player_name=prop.player.name,
                    team=prop.player.team,
                    sport=prop.player.sport,
                    stat=prop.stat.value,
                    line=prop.line,
                    projection=prop.projection,
                    edge=prop.edge,
                    confidence=prop.confidence,
                    direction=prop.direction,
                    platform=prop.platform.value,
                    game=getattr(prop, "game", ""),
                    game_time=getattr(prop, "game_time", ""),
                )

                session.add(prop_model)

            session.commit()
            return entry_model.id

        except Exception:

            session.rollback()
            raise

        finally:

            session.close()

    @staticmethod
    def pending() -> list[dict]:
        EntryRepository._ensure_schema()
        with SessionLocal() as session:
            entries = (
                session.query(EntryModel)
                .filter(EntryModel.status == "Pending")
                .order_by(EntryModel.placed_at.desc(), EntryModel.created_at.desc())
                .all()
            )

            rows: list[dict] = []
            for entry in entries:
                props = (
                    session.query(EntryPropModel)
                    .filter(EntryPropModel.entry_id == entry.id)
                    .order_by(EntryPropModel.id.asc())
                    .all()
                )
                rows.append({
                    "id": entry.id,
                    "platform": entry.platform,
                    "average_confidence": entry.average_confidence,
                    "average_edge": entry.average_edge,
                    "wager": entry.wager or 0.0,
                    "multiplier": entry.multiplier or 1.0,
                    "potential_payout": entry.potential_payout or 0.0,
                    "profit": entry.profit or 0.0,
                    "status": entry.status,
                    "result": entry.result,
                    "entry_mode": getattr(entry, "entry_mode", "real") or "real",
                    "recommended_by_app": bool(getattr(entry, "recommended_by_app", False)),
                    "audit_snapshot": getattr(entry, "audit_snapshot", "") or "",
                    "placed_at": entry.placed_at,
                    "props": [
                        {
                            "player": prop.player_name,
                            "team": prop.team,
                            "sport": prop.sport,
                            "stat": prop.stat,
                            "line": prop.line,
                            "projection": prop.projection,
                            "edge": prop.edge,
                            "confidence": prop.confidence,
                            "direction": prop.direction or "Over",
                            "platform": prop.platform,
                            "game": prop.game,
                            "game_time": getattr(prop, "game_time", "") or "",
                            "actual": getattr(prop, "actual", None),
                            "final_result": getattr(prop, "final_result", "") or "",
                            "final_source": getattr(prop, "final_source", "") or "",
                            "final_status": getattr(prop, "final_status", "") or "",
                        }
                        for prop in props
                    ],
                })

            return rows

    @staticmethod
    def all() -> list[dict]:
        EntryRepository._ensure_schema()
        with SessionLocal() as session:
            entries = (
                session.query(EntryModel)
                .order_by(EntryModel.created_at.desc(), EntryModel.id.desc())
                .all()
            )

            rows: list[dict] = []
            for entry in entries:
                props = (
                    session.query(EntryPropModel)
                    .filter(EntryPropModel.entry_id == entry.id)
                    .order_by(EntryPropModel.id.asc())
                    .all()
                )
                rows.append({
                    "id": entry.id,
                    "platform": entry.platform,
                    "average_confidence": entry.average_confidence,
                    "average_edge": entry.average_edge,
                    "grade": entry.grade,
                    "recommendation": entry.recommendation,
                    "wager": entry.wager or 0.0,
                    "multiplier": entry.multiplier or 1.0,
                    "potential_payout": entry.potential_payout or 0.0,
                    "profit": entry.profit or 0.0,
                    "status": entry.status,
                    "result": entry.result,
                    "entry_mode": getattr(entry, "entry_mode", "real") or "real",
                    "recommended_by_app": bool(getattr(entry, "recommended_by_app", False)),
                    "audit_snapshot": getattr(entry, "audit_snapshot", "") or "",
                    "placed_at": entry.placed_at,
                    "settled_at": entry.settled_at,
                    "created_at": entry.created_at,
                    "props": [
                        {
                            "player": prop.player_name,
                            "team": prop.team,
                            "sport": prop.sport,
                            "stat": prop.stat,
                            "line": prop.line,
                            "projection": prop.projection,
                            "edge": prop.edge,
                            "confidence": prop.confidence,
                            "direction": prop.direction or "Over",
                            "platform": prop.platform,
                            "game": prop.game,
                            "game_time": getattr(prop, "game_time", "") or "",
                            "actual": getattr(prop, "actual", None),
                            "final_result": getattr(prop, "final_result", "") or "",
                            "final_source": getattr(prop, "final_source", "") or "",
                            "final_status": getattr(prop, "final_status", "") or "",
                        }
                        for prop in props
                    ],
                })

            return rows

    @staticmethod
    def get_pending(entry_id: int) -> dict | None:
        entries = EntryRepository.pending()
        return next((entry for entry in entries if entry["id"] == entry_id), None)

    @staticmethod
    def settle(
        entry_id: int,
        result: str,
        dnp_legs: int = 0,
        dnp_mode: str = "reduce",
        leg_results: list[dict] | None = None,
    ) -> None:
        EntryRepository._ensure_schema()
        if result not in {"Win", "Loss", "Push", "DNP"}:
            raise ValueError("Entry result must be Win, Loss, Push, or DNP.")

        with SessionLocal() as session:
            entry = session.get(EntryModel, entry_id)
            if entry is None:
                raise ValueError(f"Entry {entry_id} was not found.")
            leg_count = (
                session.query(EntryPropModel)
                .filter(EntryPropModel.entry_id == entry.id)
                .count()
            )
            result, profit = EntryRepository._settlement_profit(
                result,
                entry.wager or 0.0,
                entry.multiplier or 1.0,
                leg_count,
                dnp_legs,
                dnp_mode,
            )
            if EntryRepository._normalize_entry_mode(getattr(entry, "entry_mode", "real")) == "paper":
                profit = 0.0

            entry.status = "Settled"
            entry.result = result
            entry.profit = profit
            entry.settled_at = utc_now()
            if leg_results:
                EntryRepository._store_leg_results(session, entry.id, leg_results)
            synced_entry = EntryRepository._entry_dict(session, entry)
            session.commit()

        EntryRepository._sync_entry_to_bet_history(synced_entry)

    @staticmethod
    def sync_settled_to_bet_history() -> dict:
        EntryRepository._ensure_schema()
        synced = 0
        with SessionLocal() as session:
            entries = (
                session.query(EntryModel)
                .filter(EntryModel.status == "Settled")
                .all()
            )
            payloads = [EntryRepository._entry_dict(session, entry) for entry in entries]

        for entry in payloads:
            EntryRepository._sync_entry_to_bet_history(entry)
            synced += 1

        return {"synced": synced}

    @staticmethod
    def store_settled_leg_results(entry_id: int, leg_results: list[dict]) -> None:
        EntryRepository._ensure_schema()
        with SessionLocal() as session:
            EntryRepository._store_leg_results(session, entry_id, leg_results)
            session.commit()

    @staticmethod
    def backfill_game_times(
        game_times: list[dict],
        pending_only: bool = False,
        overwrite: bool = False,
    ) -> dict:
        """Attach missing game start times to entry legs from provider scoreboard rows."""
        EntryRepository._ensure_schema()
        indexed = EntryRepository._index_game_times(game_times)
        if not indexed.get("records"):
            return {"updated": 0, "candidates": 0}

        updated = 0
        with SessionLocal() as session:
            query = session.query(EntryPropModel, EntryModel).join(
                EntryModel,
                EntryPropModel.entry_id == EntryModel.id,
            )
            if pending_only:
                query = query.filter(EntryModel.status == "Pending")
            if not overwrite:
                query = query.filter((EntryPropModel.game_time.is_(None)) | (EntryPropModel.game_time == ""))

            for prop, entry in query.all():
                game_time = EntryRepository._matching_game_time(prop, indexed, getattr(entry, "placed_at", None))
                if not game_time or prop.game_time == game_time:
                    continue
                prop.game_time = game_time
                updated += 1

            session.commit()

        return {"updated": updated, "candidates": len(indexed)}

    @staticmethod
    def classify_missing_economics(default_wager: float = DEFAULT_WAGER) -> dict:
        EntryRepository._ensure_schema()
        with SessionLocal() as session:
            entries = (
                session.query(EntryModel)
                .filter(EntryModel.status.in_(("Pending", "Settled")))
                .all()
            )
            updated = 0
            pending = 0
            settled = 0

            for entry in entries:
                if EntryRepository._normalize_entry_mode(getattr(entry, "entry_mode", "real")) == "paper":
                    continue
                missing_wager = not entry.wager or entry.wager <= 0
                missing_multiplier = not entry.multiplier or entry.multiplier <= 1
                if not missing_wager and not missing_multiplier:
                    continue

                leg_count = (
                    session.query(EntryPropModel)
                    .filter(EntryPropModel.entry_id == entry.id)
                    .count()
                )
                entry.wager = round(float(default_wager), 2) if missing_wager else entry.wager
                entry.multiplier = (
                    EntryRepository._default_multiplier_for_legs(leg_count)
                    if missing_multiplier
                    else entry.multiplier
                )
                entry.potential_payout = round((entry.wager or 0.0) * (entry.multiplier or 1.0), 2)
                if entry.status == "Settled":
                    entry.profit = EntryRepository._profit_for_result(
                        entry.result,
                        entry.wager or 0.0,
                        entry.multiplier or 1.0,
                    )
                    settled += 1
                else:
                    pending += 1
                updated += 1

            session.commit()
            return {
                "updated": updated,
                "pending": pending,
                "settled": settled,
                "default_wager": round(float(default_wager), 2),
            }

    @staticmethod
    def financial_stats() -> dict:
        entries = EntryRepository.all()
        active = [entry for entry in entries if entry["status"] in {"Pending", "Settled"}]
        real_active = [entry for entry in active if not EntryRepository._is_paper(entry)]
        paper_active = [entry for entry in active if EntryRepository._is_paper(entry)]
        settled = [entry for entry in real_active if entry["status"] == "Settled"]
        pending = [entry for entry in real_active if entry["status"] == "Pending"]
        paper_settled = [entry for entry in paper_active if entry["status"] == "Settled"]
        paper_pending = [entry for entry in paper_active if entry["status"] == "Pending"]
        wins = sum(1 for entry in settled if entry["result"] == "Win")
        losses = sum(1 for entry in settled if entry["result"] == "Loss")
        pushes = sum(1 for entry in settled if entry["result"] == "Push")
        total_wagered = sum(entry["wager"] for entry in real_active)
        settled_profit = sum(entry["profit"] for entry in settled)
        pending_exposure = sum(entry["wager"] for entry in pending)
        return {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "profit": round(settled_profit, 2),
            "wagered": round(total_wagered, 2),
            "pending_exposure": round(pending_exposure, 2),
            "roi": round((settled_profit / total_wagered * 100) if total_wagered else 0.0, 2),
            "recommendation_accuracy": EntryRepository._recommendation_accuracy(active),
            "paper": EntryRepository._paper_stats(paper_active, paper_settled, paper_pending),
            "by_result": EntryRepository._group_by_result(settled),
            "by_grade": EntryRepository._group_by_key(settled, lambda entry: entry.get("grade") or "Ungraded"),
            "by_sport": EntryRepository._group_by_key(settled, EntryRepository._primary_sport),
            "by_platform": EntryRepository._group_by_key(settled, lambda entry: entry.get("platform") or "Unknown"),
            "platform_profitability": EntryRepository._ranked_groups(
                EntryRepository._group_by_key(settled, lambda entry: entry.get("platform") or "Unknown")
            ),
        }

    @staticmethod
    def _recommendation_accuracy(entries: list[dict]) -> dict:
        recommended = [entry for entry in entries if entry.get("recommended_by_app")]
        settled = [entry for entry in recommended if entry.get("status") == "Settled"]
        decisions = [entry for entry in settled if entry.get("result") in {"Win", "Loss"}]
        wins = sum(1 for entry in decisions if entry.get("result") == "Win")
        losses = sum(1 for entry in decisions if entry.get("result") == "Loss")
        pushes = sum(1 for entry in settled if entry.get("result") == "Push")
        pending = sum(1 for entry in recommended if entry.get("status") == "Pending")
        total = wins + losses
        return {
            "accuracy": round((wins / total * 100) if total else 0.0, 1),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "pending": pending,
            "tracked": len(recommended),
            "settled": len(settled),
            "decisions": total,
        }

    @staticmethod
    def _paper_stats(active: list[dict], settled: list[dict], pending: list[dict]) -> dict:
        decisions = [entry for entry in settled if entry.get("result") in {"Win", "Loss"}]
        wins = sum(1 for entry in decisions if entry.get("result") == "Win")
        losses = sum(1 for entry in decisions if entry.get("result") == "Loss")
        pushes = sum(1 for entry in settled if entry.get("result") == "Push")
        avg_confidence = (
            sum(float(entry.get("average_confidence") or 0.0) for entry in decisions) / len(decisions)
            if decisions
            else 0.0
        )
        actual = (wins / len(decisions) * 100) if decisions else 0.0
        return {
            "active": len(active),
            "pending": len(pending),
            "settled": len(settled),
            "decisions": len(decisions),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "accuracy": round(actual, 1),
            "average_confidence": round(avg_confidence, 1),
            "calibration_edge": round(actual - avg_confidence, 1) if decisions else 0.0,
        }

    @staticmethod
    def _profit_for_result(result: str, wager: float, multiplier: float) -> float:
        if result == "Win":
            return round((wager * multiplier) - wager, 2)
        if result == "Loss":
            return round(-wager, 2)
        return 0.0

    @staticmethod
    def _normalize_entry_mode(entry_mode: str) -> str:
        return "paper" if str(entry_mode or "").strip().lower() == "paper" else "real"

    @staticmethod
    def _is_paper(entry: dict) -> bool:
        return EntryRepository._normalize_entry_mode(entry.get("entry_mode", "real")) == "paper"

    @staticmethod
    def _sync_entry_to_bet_history(entry: dict) -> None:
        from repository.bet_repository import BetRepository

        if entry.get("status") != "Settled" or entry.get("result") not in {"Win", "Loss", "Push", "DNP"}:
            return
        BetRepository().save_entry_result(entry)

    @staticmethod
    def _index_game_times(game_times: list[dict]) -> dict[str, list[dict]]:
        records: list[dict] = []
        for row in game_times:
            sport = str(row.get("sport") or "").upper()
            game_time = str(row.get("game_time") or "").strip()
            if not sport or not game_time:
                continue
            parts = EntryRepository._game_parts(row.get("game", ""))
            if not parts:
                continue
            records.append({
                "sport": sport,
                "game_time": game_time,
                "parts": set(parts),
                "starts_at": EntryRepository._parse_game_time(game_time),
            })
        return {"records": records}

    @staticmethod
    def _matching_game_time(
        prop: EntryPropModel,
        indexed: dict[str, list[dict]],
        placed_at: datetime | None = None,
    ) -> str:
        sport = str(getattr(prop, "sport", "") or "").upper()
        team = EntryRepository._game_token(getattr(prop, "team", ""))
        game_parts = EntryRepository._game_parts(getattr(prop, "game", ""))

        if team and game_parts:
            matched = EntryRepository._best_game_time(indexed["records"], sport, {team, *game_parts}, placed_at)
            if matched:
                return matched

        if len(game_parts) >= 2:
            matched = EntryRepository._best_game_time(indexed["records"], sport, set(game_parts), placed_at)
            if matched:
                return matched

        if team:
            matched = EntryRepository._best_game_time(indexed["records"], sport, {team}, placed_at, require_unique=True)
            if matched:
                return matched
        return ""

    @staticmethod
    def _game_lookup_tokens(value: object) -> list[str]:
        text = str(value or "").upper().strip()
        if not text:
            return []
        normalized = text.replace(" VS ", "@").replace(" V ", "@").replace(" AT ", "@")
        raw_parts = [part for part in re.split(r"[@/\-\s]+", normalized) if part]
        tokens = [EntryRepository._game_token(normalized)]
        tokens.extend(EntryRepository._game_token(part) for part in raw_parts)
        return [token for index, token in enumerate(tokens) if token and token not in tokens[:index]]

    @staticmethod
    def _game_token(value: object) -> str:
        text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
        return EntryRepository.TEAM_ALIASES.get(text, text)

    @staticmethod
    def _game_parts(value: object) -> list[str]:
        text = str(value or "").upper().strip()
        if not text:
            return []
        normalized = text.replace(" VS ", "@").replace(" V ", "@").replace(" AT ", "@")
        parts = [EntryRepository._game_token(part) for part in re.split(r"[@/\-\s]+", normalized) if part]
        return [part for index, part in enumerate(parts) if part and part not in parts[:index]]

    @staticmethod
    def _best_game_time(
        records: list[dict],
        sport: str,
        required_parts: set[str],
        placed_at: datetime | None,
        require_unique: bool = False,
    ) -> str:
        candidates = [
            record
            for record in records
            if record["sport"] == sport and required_parts.issubset(record["parts"])
        ]
        if not candidates:
            return ""
        placed = EntryRepository._aware_datetime(placed_at)
        if placed is not None:
            future = [
                candidate
                for candidate in candidates
                if candidate.get("starts_at") is not None and candidate["starts_at"] >= placed
            ]
            if future:
                candidates = future
        if require_unique and len(candidates) != 1:
            return ""
        candidates.sort(key=lambda candidate: candidate.get("starts_at") or datetime.max.replace(tzinfo=timezone.utc))
        return str(candidates[0].get("game_time") or "")

    @staticmethod
    def _parse_game_time(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return EntryRepository._aware_datetime(parsed)

    @staticmethod
    def _aware_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _store_leg_results(session: Session, entry_id: int, leg_results: list[dict]) -> None:
        props = (
            session.query(EntryPropModel)
            .filter(EntryPropModel.entry_id == entry_id)
            .order_by(EntryPropModel.id.asc())
            .all()
        )
        for prop_model, result in zip(props, leg_results, strict=False):
            actual = result.get("actual")
            prop_model.actual = float(actual) if actual is not None else None
            prop_model.final_result = str(result.get("result") or "")
            prop_model.final_source = str(result.get("source") or "")
            prop_model.final_status = str(result.get("final_status") or result.get("status") or "")

    @staticmethod
    def _entry_dict(session: Session, entry: EntryModel) -> dict:
        props = (
            session.query(EntryPropModel)
            .filter(EntryPropModel.entry_id == entry.id)
            .order_by(EntryPropModel.id.asc())
            .all()
        )
        return {
            "id": entry.id,
            "platform": entry.platform,
            "average_confidence": entry.average_confidence,
            "average_edge": entry.average_edge,
            "grade": entry.grade,
            "recommendation": entry.recommendation,
            "wager": entry.wager or 0.0,
            "multiplier": entry.multiplier or 1.0,
            "potential_payout": entry.potential_payout or 0.0,
            "profit": entry.profit or 0.0,
            "status": entry.status,
            "result": entry.result,
            "entry_mode": getattr(entry, "entry_mode", "real") or "real",
            "recommended_by_app": bool(getattr(entry, "recommended_by_app", False)),
            "audit_snapshot": getattr(entry, "audit_snapshot", "") or "",
            "placed_at": entry.placed_at,
            "settled_at": entry.settled_at,
            "created_at": entry.created_at,
            "props": [
                {
                    "player": prop.player_name,
                    "team": prop.team,
                    "sport": prop.sport,
                    "stat": prop.stat,
                    "line": prop.line,
                    "projection": prop.projection,
                    "edge": prop.edge,
                    "confidence": prop.confidence,
                    "direction": prop.direction or "Over",
                    "platform": prop.platform,
                    "game": prop.game,
                    "game_time": getattr(prop, "game_time", "") or "",
                    "actual": getattr(prop, "actual", None),
                    "final_result": getattr(prop, "final_result", "") or "",
                    "final_source": getattr(prop, "final_source", "") or "",
                    "final_status": getattr(prop, "final_status", "") or "",
                }
                for prop in props
            ],
        }

    @staticmethod
    def _settlement_profit(
        result: str,
        wager: float,
        multiplier: float,
        leg_count: int,
        dnp_legs: int = 0,
        dnp_mode: str = "reduce",
    ) -> tuple[str, float]:
        dnp_legs = max(0, min(int(dnp_legs or 0), int(leg_count or 0)))
        if result == "DNP":
            return "Push", 0.0
        if dnp_legs <= 0 or dnp_mode == "ignore":
            return result, EntryRepository._profit_for_result(result, wager, multiplier)
        if dnp_mode == "refund":
            return "Push", 0.0
        remaining_legs = max(0, int(leg_count or 0) - dnp_legs)
        if remaining_legs <= 1:
            return "Push", 0.0
        adjusted_multiplier = EntryRepository._default_multiplier_for_legs(remaining_legs)
        return result, EntryRepository._profit_for_result(result, wager, adjusted_multiplier)

    @staticmethod
    def _default_multiplier_for_legs(leg_count: int) -> float:
        return EntryRepository.DEFAULT_MULTIPLIERS.get(leg_count, 3.0)

    @staticmethod
    def _group_by_result(entries: list[dict]) -> dict[str, dict]:
        return EntryRepository._group_by_key(entries, lambda entry: entry.get("result") or "Unknown")

    @staticmethod
    def _primary_sport(entry: dict) -> str:
        props = entry.get("props") or []
        return props[0].get("sport") if props else "Unknown"

    @staticmethod
    def _group_by_key(entries: list[dict], key) -> dict[str, dict]:
        groups: dict[str, dict] = {}
        for entry in entries:
            name = key(entry) or "Unknown"
            group = groups.setdefault(
                name,
                {"entries": 0, "wins": 0, "losses": 0, "pushes": 0, "profit": 0.0, "wagered": 0.0},
            )
            group["entries"] += 1
            group["profit"] += entry.get("profit", 0.0)
            group["wagered"] += entry.get("wager", 0.0)
            if entry.get("result") == "Win":
                group["wins"] += 1
            elif entry.get("result") == "Loss":
                group["losses"] += 1
            elif entry.get("result") == "Push":
                group["pushes"] += 1

        for group in groups.values():
            decisions = group["wins"] + group["losses"]
            group["profit"] = round(group["profit"], 2)
            group["wagered"] = round(group["wagered"], 2)
            group["roi"] = round((group["profit"] / group["wagered"] * 100) if group["wagered"] else 0.0, 2)
            group["win_pct"] = round((group["wins"] / decisions * 100) if decisions else 0.0, 1)
        return groups

    @staticmethod
    def _ranked_groups(groups: dict[str, dict]) -> list[dict]:
        rows = [{"platform": name, **stats} for name, stats in groups.items()]
        rows.sort(key=lambda row: (row["profit"], row["roi"], row["wins"]), reverse=True)
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
        return rows

from datetime import datetime

from sqlalchemy.orm import Session

from repository.database import SessionLocal, initialize_database
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel

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
    ) -> int:

        EntryRepository._ensure_schema()
        session: Session = SessionLocal()

        try:
            analysis = entry_recommendation(entry)
            wager = round(float(wager or 0), 2)
            multiplier = round(float(multiplier or 1), 2)
            potential_payout = round(wager * multiplier, 2)

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
                placed_at=datetime.utcnow() if status == "Pending" else None,
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
                    platform=prop.platform.value,
                    game=getattr(prop, "game", ""),
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
                            "platform": prop.platform,
                            "game": prop.game,
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
                            "platform": prop.platform,
                            "game": prop.game,
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
    def settle(entry_id: int, result: str, dnp_legs: int = 0, dnp_mode: str = "reduce") -> None:
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

            entry.status = "Settled"
            entry.result = result
            entry.profit = profit
            entry.settled_at = datetime.utcnow()
            session.commit()

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
        settled = [entry for entry in active if entry["status"] == "Settled"]
        pending = [entry for entry in active if entry["status"] == "Pending"]
        wins = sum(1 for entry in settled if entry["result"] == "Win")
        losses = sum(1 for entry in settled if entry["result"] == "Loss")
        pushes = sum(1 for entry in settled if entry["result"] == "Push")
        total_wagered = sum(entry["wager"] for entry in active)
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
            "by_result": EntryRepository._group_by_result(settled),
            "by_grade": EntryRepository._group_by_key(settled, lambda entry: entry.get("grade") or "Ungraded"),
            "by_sport": EntryRepository._group_by_key(settled, EntryRepository._primary_sport),
            "by_platform": EntryRepository._group_by_key(settled, lambda entry: entry.get("platform") or "Unknown"),
        }

    @staticmethod
    def _profit_for_result(result: str, wager: float, multiplier: float) -> float:
        if result == "Win":
            return round((wager * multiplier) - wager, 2)
        if result == "Loss":
            return round(-wager, 2)
        return 0.0

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

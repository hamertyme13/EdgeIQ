from datetime import datetime

from sqlalchemy.orm import Session

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel

from models.entry import Entry
from analytics.entry_recommendation import recommendation as entry_recommendation


class EntryRepository:

    @staticmethod
    def save(entry: Entry, status: str = "Draft", result: str = "") -> int:

        session: Session = SessionLocal()

        try:
            analysis = entry_recommendation(entry)

            entry_model = EntryModel(
                platform=entry.platform.value,
                average_confidence=entry.average_confidence,
                average_edge=entry.average_edge,
                grade=analysis["grade"],
                recommendation=analysis["action"],
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
    def settle(entry_id: int, result: str) -> None:
        if result not in {"Win", "Loss", "Push"}:
            raise ValueError("Entry result must be Win, Loss, or Push.")

        with SessionLocal() as session:
            entry = session.get(EntryModel, entry_id)
            if entry is None:
                raise ValueError(f"Entry {entry_id} was not found.")

            entry.status = "Settled"
            entry.result = result
            entry.settled_at = datetime.utcnow()
            session.commit()

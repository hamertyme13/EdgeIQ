from sqlalchemy.orm import Session

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel

from models.entry import Entry


class EntryRepository:

    @staticmethod
    def save(entry: Entry):

        session: Session = SessionLocal()

        try:

            entry_model = EntryModel(
                platform=entry.platform.value,
                average_confidence=entry.average_confidence,
                average_edge=entry.average_edge,
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
                )

                session.add(prop_model)
                session.commit()

        except Exception:

            session.rollback()
            raise

        finally:

            session.close()
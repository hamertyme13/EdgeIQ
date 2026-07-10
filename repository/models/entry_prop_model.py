from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
)

from repository.database import Base


class EntryPropModel(Base):

    __tablename__ = "entry_props"

    id = Column(Integer, primary_key=True)

    entry_id = Column(
        Integer,
        ForeignKey("entries.id"),
        nullable=False,
    )

    player_name = Column(String)

    team = Column(String)

    sport = Column(String)

    stat = Column(String)

    line = Column(Float)

    projection = Column(Float)

    edge = Column(Float)

    confidence = Column(Float)

    direction = Column(String)

    platform = Column(String)

    game = Column(String)

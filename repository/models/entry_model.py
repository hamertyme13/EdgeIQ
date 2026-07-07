from sqlalchemy import Column, Integer, Float, String, DateTime, func

from repository.database import Base


class EntryModel(Base):

    __tablename__ = "entries"

    id = Column(Integer, primary_key=True)

    platform = Column(String, nullable=False)

    average_confidence = Column(Float, nullable=False)

    average_edge = Column(Float, nullable=False)

    grade = Column(String)

    recommendation = Column(String)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )
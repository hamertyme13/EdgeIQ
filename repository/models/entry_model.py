from sqlalchemy import Boolean, Column, Integer, Float, String, DateTime, Text, func

from repository.database import Base


class EntryModel(Base):

    __tablename__ = "entries"

    id = Column(Integer, primary_key=True)

    platform = Column(String, nullable=False)

    average_confidence = Column(Float, nullable=False)

    average_edge = Column(Float, nullable=False)

    grade = Column(String)

    recommendation = Column(String)

    wager = Column(Float, nullable=False, default=0.0)

    multiplier = Column(Float, nullable=False, default=1.0)

    potential_payout = Column(Float, nullable=False, default=0.0)

    profit = Column(Float, nullable=False, default=0.0)

    status = Column(String, nullable=False, default="Draft")

    result = Column(String, nullable=False, default="")

    entry_mode = Column(String, nullable=False, default="real")

    placed_at = Column(DateTime)

    settled_at = Column(DateTime)

    recommended_by_app = Column(Boolean, nullable=False, default=False)

    audit_snapshot = Column(Text, nullable=False, default="")

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

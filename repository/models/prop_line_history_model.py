from sqlalchemy import Column, DateTime, Float, Integer, String, func

from repository.database import Base


class PropLineHistoryModel(Base):
    """Stores a snapshot of a prop line at a point in time."""

    __tablename__ = "prop_line_history"

    id         = Column(Integer, primary_key=True)
    player     = Column(String,  nullable=False, index=True)
    stat       = Column(String,  nullable=False)
    platform   = Column(String,  nullable=False)
    line       = Column(Float,   nullable=False)
    game       = Column(String, default="")
    game_time  = Column(String, default="")
    line_offer_type = Column(String, default="standard")
    recorded_at = Column(DateTime, server_default=func.now(), nullable=False)

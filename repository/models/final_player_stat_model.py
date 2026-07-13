from sqlalchemy import Column, DateTime, Float, Integer, String, func

from repository.database import Base


class FinalPlayerStatModel(Base):
    """Stores finalized player stat results used for hit rates and settlement."""

    __tablename__ = "final_player_stats"

    id = Column(Integer, primary_key=True)
    player = Column(String, nullable=False, index=True)
    team = Column(String, default="")
    sport = Column(String, nullable=False, index=True)
    stat = Column(String, nullable=False, index=True)
    game = Column(String, default="")
    game_date = Column(String, default="")
    actual = Column(Float, nullable=False)
    status = Column(String, default="played")
    source = Column(String, default="import")
    imported_at = Column(DateTime, server_default=func.now(), nullable=False)

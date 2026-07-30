from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from repository.database import Base


class BetEntity(Base):

    __tablename__ = "bets"

    id = Column(Integer, primary_key=True)

    sport = Column(String)

    game = Column(String)

    description = Column(String)

    odds = Column(Integer)

    wager = Column(Float)

    result = Column(String)

    profit = Column(Float)

    platform = Column(String, default="")

    stat_type = Column(String, default="")

    win_probability = Column(Float, default=0.0)

    source = Column(String, default="manual")

    source_entry_id = Column(Integer)

    entry_mode = Column(String, default="real")

    payout_type = Column(String, default="standard")

    payout_table_snapshot = Column(Text, default="")

    expected_return = Column(Float, default=0.0)

    expected_value = Column(Float, default=0.0)

    created_at = Column(DateTime, server_default=func.now())

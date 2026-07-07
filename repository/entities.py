from sqlalchemy import Column, Float, Integer, String

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
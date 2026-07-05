from models.bet import Bet
from repository.entities import BetEntity
from repository.database import SessionLocal


class BetRepository:

    def save(self, bet: Bet):

        session = SessionLocal()

        entity = BetEntity(
            sport=bet.sport,
            game=bet.game,
            description=bet.description,
            odds=bet.odds,
            wager=bet.wager,
            result=bet.result,
            profit=bet.profit,
        )

        session.add(entity)
        session.commit()
        session.close()
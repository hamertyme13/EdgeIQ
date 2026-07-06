from models.bet import Bet
from repository.database import SessionLocal
from repository.entities import BetEntity


class BetRepository:

    def save(self, bet: Bet) -> None:
        session = SessionLocal()

        try:
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

        finally:
            session.close()

    def get_all(self) -> list[Bet]:

        session = SessionLocal()

        try:

            entities = session.query(BetEntity).all()

            bets = []

            for entity in entities:

                bets.append(
                    Bet(
                        sport=entity.sport,
                        game=entity.game,
                        description=entity.description,
                        odds=entity.odds,
                        wager=entity.wager,
                        result=entity.result,
                        profit=entity.profit,
                    )
                )

            return bets

        finally:

            session.close()
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

    def count(self) -> int:

        session = SessionLocal()

        try:

            return session.query(BetEntity).count()

        finally:

            session.close()

    def total_profit(self) -> float:

        bets = self.get_all()
        return sum(bet.profit for bet in bets)
    
    def dashboard_stats(self) -> dict:

        bets = self.get_all()

        wins = 0
        losses = 0

        total_profit = 0
        total_wagered = 0

        wagers = []
        profits = []

        for bet in bets:
            wagers.append(bet.wager)
            profits.append(bet.profit)

            total_profit += bet.profit
            total_wagered += bet.wager

            if bet.result == "Win":
                wins += 1
            else:
                losses += 1

        roi = (total_profit / total_wagered) * 100 if total_wagered else 0
        average = sum(wagers) / len(wagers) if wagers else 0

        return {
            "wins": wins,
            "losses": losses,
            "record": f"{wins}-{losses}",
            "profit": total_profit,
            "wagered": total_wagered,
            "roi": roi,
            "average": average,
            "largest_win": max(profits) if profits else 0,
            "largest_loss": min(profits) if profits else 0,
        }
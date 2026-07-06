from models.bet import Bet
from repository.entities import BetEntity


def entity_to_bet(entity: BetEntity) -> Bet:
    return Bet(
        sport=entity.sport,
        game=entity.game,
        description=entity.description,
        odds=entity.odds,
        wager=entity.wager,
        result=entity.result,
        profit=entity.profit,
    )
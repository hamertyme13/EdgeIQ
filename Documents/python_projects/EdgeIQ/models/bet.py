from dataclasses import dataclass

@dataclass
class Bet:
    sport: str
    game: str
    description: str
    odds: int
    wager: float
    result: str
    profit: float
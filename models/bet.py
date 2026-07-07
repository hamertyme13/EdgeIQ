from dataclasses import dataclass, field


@dataclass
class Bet:
    sport: str
    game: str
    description: str
    odds: int
    wager: float
    result: str
    profit: float
    platform: str = ""
    stat_type: str = ""
    win_probability: float = 0.0
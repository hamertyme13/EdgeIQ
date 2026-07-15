from dataclasses import dataclass, field
from datetime import datetime


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
    source: str = "manual"
    source_entry_id: int | None = None
    entry_mode: str = "real"
    created_at: datetime | None = None

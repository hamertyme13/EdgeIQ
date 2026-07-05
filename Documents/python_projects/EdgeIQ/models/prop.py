from dataclasses import dataclass

from models.stat_type import StatType

stat: StatType

@dataclass
class Prop:

    player: Player

    stat: str

    line: float

    projection: float

    confidence: float = 0.0
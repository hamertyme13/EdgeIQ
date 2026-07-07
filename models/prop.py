from dataclasses import dataclass

from models.player import Player
from models.platform import Platform
from models.stat_type import StatType


@dataclass
class Prop:

    player: Player

    stat: StatType

    line: float

    projection: float

    edge: float

    confidence: float

    platform: Platform = Platform.PRIZEPICKS

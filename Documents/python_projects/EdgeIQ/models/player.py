from dataclasses import dataclass


@dataclass
class Player:
    name: str
    team: str
    sport: str
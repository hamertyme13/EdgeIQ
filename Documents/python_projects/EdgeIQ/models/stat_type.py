from enum import Enum


class StatType(Enum):
    POINTS = "Points"
    REBOUNDS = "Rebounds"
    ASSISTS = "Assists"
    PRA = "Points + Rebounds + Assists"
    THREES = "3-Pointers Made"
    BLOCKS = "Blocks"
    STEALS = "Steals"
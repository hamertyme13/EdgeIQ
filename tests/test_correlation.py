from analytics.correlation import detect_correlations

from models.player import Player
from models.prop import Prop
from models.entry import Entry
from models.platform import Platform
from models.stat_type import StatType


player1 = Player(
    name="A'ja Wilson",
    team="Aces",
    sport="WNBA",
)

player2 = Player(
    name="Chelsea Gray",
    team="Aces",
    sport="WNBA",
)

prop1 = Prop(
    player=player1,
    stat=StatType.PRA,
    line=27.5,
    projection=30,
    edge=2.5,
    confidence=70,
)

prop2 = Prop(
    player=player2,
    stat=StatType.ASSISTS,
    line=6.5,
    projection=8,
    edge=1.5,
    confidence=65,
)

entry = Entry(
    platform=Platform.PRIZEPICKS,
    props=[prop1, prop2],
)

warnings = detect_correlations(entry)

print("\nCorrelation Warnings")
print("--------------------")

for warning in warnings:
    print(f"• {warning}")
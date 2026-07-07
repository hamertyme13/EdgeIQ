from models.player import Player
from models.prop import Prop
from models.stat_type import StatType

from ui.prop_analysis import display_prop_analysis

player = Player(
    name="Caitlin Clark",
    team="Indiana Fever",
    sport="WNBA",
)

prop = Prop(
    player=player,
    stat=StatType.ASSISTS,
    line=8.5,
    projection=9.7,
    edge=1.2,
    confidence=64,
)

display_prop_analysis(prop)
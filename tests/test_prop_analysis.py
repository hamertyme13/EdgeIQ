from models.player import Player
from models.platform import Platform
from models.prop import Prop
from models.stat_type import StatType

from analytics.prop_recommendation import recommendation
from ui.prop_analysis import display_prop_analysis


def _prop(edge: float = 1.2) -> Prop:
    return Prop(
        player=Player(
            name="Caitlin Clark",
            team="Indiana Fever",
            sport="WNBA",
        ),
        stat=StatType.ASSISTS,
        line=8.5,
        projection=9.7,
        edge=edge,
        confidence=64,
        platform=Platform.PRIZEPICKS,
    )


def test_prop_recommendation_uses_prop_edge():
    result = recommendation(_prop())

    assert result["grade"] == "B"
    assert result["action"] == "Consider"


def test_display_prop_analysis_renders_without_error():
    display_prop_analysis(_prop())

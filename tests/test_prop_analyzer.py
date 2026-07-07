from analytics.analyzers.prop_analyzer import PropAnalyzer
from analytics.defense_vs_position import MatchupAnalysis
from models.player import Player
from models.prop import Prop

from models.stat_type import StatType


def test_prop_analyzer_applies_matchup_adjustments():
    prop = Prop(
        player=Player(name="A'ja Wilson", team="Storm", sport="WNBA"),
        stat=StatType.POINTS,
        line=22.5,
        projection=25.0,
        edge=2.5,
        confidence=78,
    )
    matchup = MatchupAnalysis(
        opponent="Storm",
        stat=StatType.POINTS,
        rank=5,
        modifier=-0.10,
        description="Elite Defense",
        confidence_adjustment=-0.05,
    )

    analysis = PropAnalyzer().analyze(prop, matchup)

    assert analysis.prop == prop
    assert analysis.matchup == matchup
    assert analysis.projected_edge == 2.4
    assert analysis.confidence == 77.95
    assert analysis.recommendation == "Pass"

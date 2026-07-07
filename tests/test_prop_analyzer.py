from analytics.analyzers.prop_analyzer import PropAnalyzer
from analytics.defense_vs_position import MatchupAnalysis
from models.player import Player
from models.prop import Prop

from models.stat_type import StatType


player = Player(
    name="A'ja Wilson",
    team="Storm",
    sport="WNBA",
)

prop = Prop(
    player=player,
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

print()
print("Prop Analysis")
print("----------------")
print("Player:", analysis.prop.player.name)

if analysis.matchup:
    print("Opponent:", analysis.matchup.opponent)
    print("Defense Rank:", analysis.matchup.rank)
    print("Modifier:", analysis.matchup.modifier)
    print("Confidence Adj:", analysis.matchup.confidence_adjustment)
    print("Description:", analysis.matchup.description)

print("Projected Edge:", analysis.projected_edge)
print("Confidence:", analysis.confidence)
print("Recommendation:", analysis.recommendation)
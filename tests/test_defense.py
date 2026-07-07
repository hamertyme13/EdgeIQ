from analytics.defense_vs_position import analyze_matchup
from models.stat_type import StatType


def test_analyze_matchup_returns_defense_context():
    analysis = analyze_matchup("Storm", StatType.ASSISTS)

    assert analysis is not None
    assert analysis.opponent == "Storm"
    assert analysis.stat == StatType.ASSISTS
    assert analysis.description

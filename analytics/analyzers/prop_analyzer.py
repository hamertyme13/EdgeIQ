from analytics.analyzers.prop_analysis import PropAnalysis
from analytics.defense_vs_position import analyze_matchup


class PropAnalyzer:

    def analyze(self, prop, defense):
        edge = prop.edge + defense.modifier
        confidence = max(0, min(100, prop.confidence + defense.confidence_adjustment))

        recommendation = self._get_recommendation(edge, confidence)

        return PropAnalysis(
            player=prop.player.name,
            opponent=defense.opponent,
            defense_rank=defense.rank,
            modifier=defense.modifier,
            confidence_adjustment=defense.confidence_adjustment,
            prop=prop,
            matchup=defense,
            projected_edge=edge,
            confidence=confidence,
            recommendation=recommendation,
        )

    def _get_recommendation(self, edge, confidence):
        if confidence >= 85 and edge >= 5:
            return "Strong Over"
        elif confidence >= 75 and edge >= 3:
            return "Lean Over"
        elif confidence >= 70 and edge > -5:
            return "Pass"
        elif confidence >= 60 and edge > -3:
            return "Lean Under"
        else:
            return "Strong Under"
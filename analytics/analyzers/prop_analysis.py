from dataclasses import dataclass

from analytics.defense_vs_position import MatchupAnalysis
from models.prop import Prop


@dataclass
class PropAnalysis:
    player: str

    opponent: str

    defense_rank: int

    modifier: float

    confidence_adjustment: float

    prop: Prop

    matchup: MatchupAnalysis | None

    projected_edge: float

    confidence: float

    recommendation: str
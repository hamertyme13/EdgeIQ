from dataclasses import dataclass
from models.stat_type import StatType

from data.wnba.models import DefenseProfile
from services.defense_service import DefenseService

def get_defense_profile(team: str) -> DefenseProfile | None:
    return DefenseService.get_profile(team)

    
def defense_rank(team: str, stat: StatType) -> int | None:

        profile = get_defense_profile(team)

        if profile is None:
            return None
        if stat == StatType.POINTS:
            return profile.vs_points_rank
        elif stat == StatType.REBOUNDS:
            return profile.vs_rebounds_rank
        elif stat == StatType.ASSISTS:
            return profile.vs_assists_rank
        else:
            return profile.vs_pra_rank
        
@dataclass
class MatchupAnalysis:
     opponent: str
     stat: StatType
     rank: int
     modifier: float
     description: str
     confidence_adjustment: float

def defense_modifier(
        opponent: str,
        stat: StatType,
        rank: int
) -> MatchupAnalysis:

    if rank <= 5:
        return MatchupAnalysis(
            opponent=opponent,
            stat=stat,
            rank=rank,
            modifier=-0.10,
            description="Elite Defense",
            confidence_adjustment=-0.05,
        )

    elif rank <= 10:
        return MatchupAnalysis(
            opponent=opponent,
            stat=stat,
            rank=rank,
            modifier=-0.05,
            description="Strong Defense",
            confidence_adjustment=-0.02
        )

    elif rank <= 20:
        return MatchupAnalysis(
            opponent=opponent,
            stat=stat,
            rank=rank,
            modifier=0.00,
            description="Average Defense",
            confidence_adjustment=0.00
        )

    elif rank <= 25:
        return MatchupAnalysis(
            opponent=opponent,
            stat=stat,
            rank=rank,
            modifier=0.05,
            description="Weak Defense",
            confidence_adjustment=0.02
        )

    return MatchupAnalysis(
        opponent=opponent,
        stat=stat,
        rank=rank,
        modifier=0.10,
        description="Very Weak Defense",
        confidence_adjustment=0.05
    )

def analyze_matchup(team: str, stat: StatType) -> MatchupAnalysis | None:
    """
    Analyze how an opponent defends a given statistic.

    Returns a MatchupAnalysis object containing:
    - defensive rank
    - projection modifier
    - confidence adjustment
    - human-readable description
    """
    rank = defense_rank(team, stat)

    if rank is None:
        return None

    return defense_modifier(
        opponent=team,
        stat=stat,
        rank=rank,
    )
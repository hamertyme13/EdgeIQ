from dataclasses import dataclass
from models.stat_type import StatType


@dataclass
class DefenseProfile:
    team: str

    vs_points_rank: int
    vs_rebounds_rank: int
    vs_assists_rank: int
    vs_pra_rank: int

DEFENSE_DATABASE = {
        "Aces": DefenseProfile(
            team="Aces",

            vs_points_rank=2,
            vs_rebounds_rank=4,
            vs_assists_rank=8,
            vs_pra_rank=3,
        ),

        "Liberty": DefenseProfile(
            team="Liberty",

            vs_points_rank=10,
            vs_rebounds_rank=9,
            vs_assists_rank=14,
            vs_pra_rank=11,
        ),

        "Fever": DefenseProfile(
            team="Fever",

            vs_points_rank=11,
            vs_rebounds_rank=12,
            vs_assists_rank=10,
            vs_pra_rank=13,
        ),

        "Storm": DefenseProfile(
            team="Storm",

            vs_points_rank=5,
            vs_rebounds_rank=6,
            vs_assists_rank=4,
            vs_pra_rank=5,
        ),
    }

def get_defense_profile(team: str):

        return DEFENSE_DATABASE.get(team)
    
def defense_rank(team: str, stat: StatType):

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
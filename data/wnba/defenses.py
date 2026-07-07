from analytics.defense_vs_position import DefenseProfile
from data.wnba.models import DefenseProfile

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
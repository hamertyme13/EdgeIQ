from dataclasses import dataclass


@dataclass
class DefenseProfile:
    team: str
    vs_points_rank: int
    vs_rebounds_rank: int
    vs_assists_rank: int
    vs_pra_rank: int
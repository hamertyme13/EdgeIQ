from analytics.defense_vs_position import analyze_matchup
from models.stat_type import StatType

analysis = analyze_matchup(
    "Storm",
    StatType.ASSISTS,
)

print()

print("Defense Analysis")
print("----------------")

print("Rank:", analysis.rank)
print("Modifier:", analysis.modifier)
print("Description:", analysis.description)
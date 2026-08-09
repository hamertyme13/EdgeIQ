from models.stat_type import StatType
from utils.stat_normalization import canonical_stat_label, stat_type_from_text


def test_nfl_provider_abbreviations_map_to_canonical_markets() -> None:
    assert stat_type_from_text("Pass Yards") == StatType.PASSING_YARDS
    assert stat_type_from_text("Rush Yards") == StatType.RUSHING_YARDS
    assert stat_type_from_text("Rec Yards") == StatType.RECEIVING_YARDS
    assert stat_type_from_text("Pass TDs") == StatType.PASSING_TDS
    assert stat_type_from_text("Rush + Rec Yards") == StatType.RUSH_RECEIVING_YARDS
    assert stat_type_from_text("Rush + Rec TDs") == StatType.RUSH_RECEIVING_TDS
    assert stat_type_from_text("INTs Thrown") == StatType.INTERCEPTIONS
    assert stat_type_from_text("XP Made") == StatType.EXTRA_POINTS_MADE


def test_short_nfl_alias_does_not_match_unrelated_stat() -> None:
    assert canonical_stat_label("Points") == "Points"

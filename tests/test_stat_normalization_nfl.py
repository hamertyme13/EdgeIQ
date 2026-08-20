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
    assert stat_type_from_text("XPM") == StatType.EXTRA_POINTS_MADE
    assert stat_type_from_text("Extra Points Attempted") == StatType.EXTRA_POINTS_ATTEMPTED
    assert stat_type_from_text("Pass + Rush Yards") == StatType.PASS_RUSH_YARDS
    assert stat_type_from_text("Solo Tackles") == StatType.SOLO_TACKLES


def test_basketball_shooting_aliases_map_to_distinct_markets() -> None:
    assert stat_type_from_text("FGA") == StatType.FIELD_GOALS_ATTEMPTED
    assert stat_type_from_text("FGM") == StatType.FIELD_GOALS_MADE
    assert stat_type_from_text("3PA") == StatType.THREES_ATTEMPTED
    assert stat_type_from_text("FTA") == StatType.FREE_THROWS_ATTEMPTED
    assert stat_type_from_text("Stls + Blks") == StatType.STEALS_BLOCKS


def test_short_nfl_alias_does_not_match_unrelated_stat() -> None:
    assert canonical_stat_label("Points") == "Points"

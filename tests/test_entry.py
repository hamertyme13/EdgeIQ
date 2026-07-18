from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from analytics.entry_recommendation import recommendation
from analytics.correlation import detect_correlations
from analytics.prop_metrics import calculate_confidence


def test_entry_defaults_to_empty_props():
    entry = Entry(platform=Platform.PRIZEPICKS)

    assert entry.prop_count == 0
    assert entry.average_confidence == 0
    assert entry.average_edge == 0
    assert entry.is_empty is True


def test_negative_edge_lowers_confidence():
    assert calculate_confidence(-2.0) == 30
    assert calculate_confidence(2.0) == 70


def test_confidence_is_stat_and_sport_aware_without_changing_default():
    assert calculate_confidence(2.0) == 70
    assert calculate_confidence(2.0, stat="Points + Rebounds + Assists", sport="NBA") < 70
    assert calculate_confidence(2.0, stat="Assists", sport="WNBA") > calculate_confidence(2.0, stat="PRA", sport="NBA")


def test_entry_recommendation_blends_confidence_edge_and_sources():
    entry = Entry(platform=Platform.PRIZEPICKS)
    entry.add_prop(
        Prop(
            player=Player(name="A", team="AAA", sport="WNBA"),
            stat=StatType.POINTS,
            line=20.5,
            projection=22.0,
            edge=1.5,
            confidence=65,
            platform=Platform.PRIZEPICKS,
            source_score=4.0,
        )
    )
    entry.add_prop(
        Prop(
            player=Player(name="B", team="BBB", sport="WNBA"),
            stat=StatType.ASSISTS,
            line=7.5,
            projection=8.6,
            edge=1.1,
            confidence=61,
            platform=Platform.PRIZEPICKS,
            source_score=2.0,
        )
    )

    result = recommendation(entry)

    assert result["grade"] == "B"
    assert result["score"] >= 66
    assert result["components"]["average_source_score"] == 3.0


def test_correlation_engine_flags_same_game_and_football_stack():
    entry = Entry(platform=Platform.PRIZEPICKS)
    entry.add_prop(
        Prop(
            player=Player(name="QB", team="AAA", sport="NFL"),
            stat=StatType.PASSING_YARDS,
            line=250.5,
            projection=270,
            edge=19.5,
            confidence=70,
            platform=Platform.PRIZEPICKS,
            game="AAA-BBB",
        )
    )
    entry.add_prop(
        Prop(
            player=Player(name="WR", team="AAA", sport="NFL"),
            stat=StatType.RECEIVING_YARDS,
            line=70.5,
            projection=80,
            edge=9.5,
            confidence=66,
            platform=Platform.PRIZEPICKS,
            game="AAA-BBB",
        )
    )

    warnings = detect_correlations(entry)

    assert any("same-game" in warning for warning in warnings)
    assert any("QB passing yards" in warning for warning in warnings)

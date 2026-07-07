from analytics.correlation import detect_correlations

from models.player import Player
from models.prop import Prop
from models.entry import Entry
from models.platform import Platform
from models.stat_type import StatType


def test_detect_correlations_flags_teammates():
    prop1 = Prop(
        player=Player(name="A'ja Wilson", team="Aces", sport="WNBA"),
        stat=StatType.PRA,
        line=27.5,
        projection=30,
        edge=2.5,
        confidence=70,
    )

    prop2 = Prop(
        player=Player(name="Chelsea Gray", team="Aces", sport="WNBA"),
        stat=StatType.ASSISTS,
        line=6.5,
        projection=8,
        edge=1.5,
        confidence=65,
    )

    entry = Entry(platform=Platform.PRIZEPICKS, props=[prop1, prop2])

    assert detect_correlations(entry) == ["Aces: multiple teammates selected."]


def test_detect_correlations_checks_all_pairs():
    props = [
        Prop(Player("A", "One", "WNBA"), StatType.POINTS, 10, 11, 1, 60),
        Prop(Player("B", "Two", "WNBA"), StatType.ASSISTS, 5, 6, 1, 60),
        Prop(Player("C", "One", "WNBA"), StatType.REBOUNDS, 7, 8, 1, 60),
    ]

    warnings = detect_correlations(Entry(platform=Platform.PRIZEPICKS, props=props))

    assert "One: multiple teammates selected." in warnings

from analytics.pipeline_types import AnalyzedProp, DataQuality
from utils.platforms import canonical_platform, maximum_entry_legs
from utils.sports import canonical_sport, sport_filter
from utils.ttl_cache import TTLMap


def test_canonical_platform_aliases_and_limits() -> None:
    assert canonical_platform("Prize Picks") == "PrizePicks"
    assert canonical_platform("dk pick6") == "DraftKings Pick6"
    assert canonical_platform("all platforms") == "Both"
    assert maximum_entry_legs("underdog fantasy") == 8
    assert maximum_entry_legs("DraftKings") == 6


def test_canonical_sport_aliases_and_all_sports_filter() -> None:
    assert canonical_sport("college football") == "NCAAF"
    assert canonical_sport("League of Legends") == "LOL"
    assert canonical_sport("unknown", default="WNBA") == "WNBA"
    assert sport_filter("All Sports") is None


def test_ttl_map_expires_and_evicts_oldest(monkeypatch) -> None:
    clock = iter((10.0, 10.0, 11.0, 11.0, 12.0, 16.0))
    monkeypatch.setattr("utils.ttl_cache.time.monotonic", lambda: next(clock))
    cache: TTLMap[str, int] = TTLMap(max_size=2)

    cache.set("first", 1, ttl=10)
    cache.set("second", 2, ttl=10)
    cache.set("third", 3, ttl=10)

    assert cache.get("first") is None
    assert cache.get("second") == 2
    assert cache.get("third") == 3


def test_typed_analyzed_prop_serializes_for_legacy_api() -> None:
    prop = AnalyzedProp(
        player="Example Player",
        stat="Points",
        line=20.5,
        direction="Over",
        platform="PrizePicks",
        sport="WNBA",
        projection=22.0,
        edge=1.5,
        confidence=61.0,
        grade="B",
        ev_percent=4.2,
        data_quality=DataQuality(score=82.0, label="Strong", sample_size=24),
    )

    payload = prop.to_dict()
    assert payload["player"] == "Example Player"
    assert payload["data_quality"] == {
        "score": 82.0,
        "label": "Strong",
        "sample_size": 24,
        "reasons": [],
    }

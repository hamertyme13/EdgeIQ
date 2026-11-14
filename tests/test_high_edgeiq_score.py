from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from repository.database import Base
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.repositories import entry_repository
from repository.repositories.entry_repository import EntryRepository
from web import app as web_app
from web.schemas.entries import AutoPaperCalibrationPayload


def test_saved_card_score_is_distinct_from_probability():
    entries = [
        {"status": "Settled", "result": "Win", "audit_snapshot": '{"recommendation":{"score":139},"model_payout_analysis":{"all_hit_probability":54}}'},
        {"status": "Settled", "result": "Loss", "audit_snapshot": {"recommendation": {"score": 91}}},
        {"status": "Settled", "result": "Win", "audit_snapshot": {"recommendation": {"score": 89}}},
        {"status": "Pending", "result": "", "audit_snapshot": {"recommendation": {"score": 100}}},
        {"status": "Settled", "result": "Win", "audit_snapshot": {"recommendation": {"score": "NaN"}}},
    ]
    stats = EntryRepository._recommendation_accuracy(entries)["high_edgeiq_score"]
    assert (stats["wins"], stats["losses"], stats["pending"], stats["tracked"]) == (1, 1, 1, 3)
    assert stats["accuracy"] == 50.0


def test_auto_sample_requires_a_saved_ninety_plus_card_score(monkeypatch):
    suggestions = [SimpleNamespace(score=89), SimpleNamespace(score=101)]
    monkeypatch.setattr(web_app, "_paper_calibration_suggestions", lambda *args, **kwargs: suggestions)
    chosen = []

    def append(suggestion, target, *_args):
        chosen.append((suggestion.score, target))
        return True

    monkeypatch.setattr(web_app, "_append_calibration_entry", append)
    result = web_app._create_high_score_calibration_card(
        AutoPaperCalibrationPayload(sport="WNBA", standard_batch=True, dry_run=True),
        {}, set(), [], [], {}, {},
    )
    assert result == {"status": "created", "created": True, "card_score": 101.0}
    assert chosen[0][1]["type"] == "HighEdgeIQScore"


def test_yesterday_hits_includes_winning_legs_from_losing_entries(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EntryModel.__table__, EntryPropModel.__table__])
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(entry_repository, "SessionLocal", session_factory)
    monkeypatch.setattr(EntryRepository, "_ensure_schema", lambda: None)
    yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    game_time = datetime.combine(yesterday, datetime.min.time(), tzinfo=ZoneInfo("America/New_York"))
    game_time = game_time.replace(hour=20).astimezone(UTC).isoformat()
    with session_factory() as session:
        session.add(EntryModel(id=1, platform="PrizePicks", average_confidence=50, average_edge=0,
                               wager=0, multiplier=1, status="Settled", result="Loss"))
        session.add_all([
            EntryPropModel(entry_id=1, player_name="A Player", sport="NBA", stat="Points", direction="Over",
                           line=20.5, actual=24, platform="PrizePicks", game="A vs B", game_time=game_time,
                           final_result="Win", final_source="verified_box_score"),
            EntryPropModel(entry_id=1, player_name="B Player", sport="NBA", stat="Assists", direction="Under",
                           line=6.5, actual=8, platform="PrizePicks", game="A vs B", game_time=game_time,
                           final_result="Loss", final_source="verified_box_score"),
        ])
        session.commit()
    result = EntryRepository.yesterday_winning_props()
    assert result["date"] == yesterday.isoformat()
    assert [(group["sport"], group["props"][0]["player"]) for group in result["sports"]] == [("NBA", "A Player")]

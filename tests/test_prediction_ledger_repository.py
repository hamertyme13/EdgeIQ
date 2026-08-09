from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository


def test_saved_entry_records_versioned_prediction_and_appends_outcome() -> None:
    prop = Prop(
        player=Player("Ledger Player", "AAA", "WNBA"),
        stat=StatType.POINTS,
        line=20.5,
        projection=22.0,
        edge=1.5,
        confidence=61.0,
        direction="Over",
        platform=Platform.PRIZEPICKS,
        game="AAA@BBB",
        game_time="2026-07-25T19:00:00Z",
        projection_source="verified_history_distribution",
        model_version="test-model-v1",
        feature_as_of="2026-07-25T12:00:00Z",
        forecast_snapshot={"sample_size": 30, "paid_eligible": True},
        forecast_paid_eligible=True,
    )
    entry_id = EntryRepository.save(
        Entry(platform=Platform.PRIZEPICKS, props=[prop]),
        status="Pending",
        entry_mode="paper",
    )

    before = [row for row in PredictionLedgerRepository.evidence_rows() if row["entry_id"] == entry_id]
    assert len(before) == 1
    assert before[0]["model_version"] == "test-model-v1"
    assert before[0]["result"] == ""

    EntryRepository.settle(
        entry_id,
        "Win",
        leg_results=[{"actual": 24.0, "result": "Win", "source": "espn", "status": "played"}],
    )
    after = [row for row in PredictionLedgerRepository.evidence_rows() if row["entry_id"] == entry_id]

    assert after[0]["projection"] == 22.0
    assert after[0]["probability"] == 61.0
    assert after[0]["result"] == "Win"
    assert after[0]["actual"] == 24.0


def test_unavailable_recheck_does_not_erase_verified_leg_result() -> None:
    prop = Prop(
        player=Player("Monotonic Result", "AAA", "WNBA"),
        stat=StatType.POINTS,
        line=20.5,
        projection=22.0,
        edge=1.5,
        confidence=61.0,
        direction="Over",
        platform=Platform.PRIZEPICKS,
        game="AAA@BBB",
        game_time="2026-07-25T19:00:00Z",
    )
    entry_id = EntryRepository.save(
        Entry(platform=Platform.PRIZEPICKS, props=[prop]),
        status="Pending",
        entry_mode="paper",
    )
    EntryRepository.settle(
        entry_id,
        "Win",
        leg_results=[{
            "actual": 24.0,
            "result": "Win",
            "source": "espn",
            "final_status": "played",
        }],
    )

    EntryRepository.store_settled_leg_results(entry_id, [{
        "actual": None,
        "result": "Unknown",
        "source": "unmatched",
        "final_status": "unknown",
    }])

    stored = next(entry for entry in EntryRepository.all() if entry["id"] == entry_id)["props"][0]
    assert stored["actual"] == 24.0
    assert stored["final_result"] == "Win"
    assert stored["final_source"] == "espn"
    assert stored["final_status"] == "played"

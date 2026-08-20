from repository.bet_repository import BetRepository
from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.repositories.entry_repository import EntryRepository


def test_repository_can_count_bets():
    repo = BetRepository()

    assert isinstance(repo.count(), int)


def test_game_time_backfill_reports_player_name_without_crashing() -> None:
    with SessionLocal() as session:
        entry = EntryModel(
            platform="PrizePicks",
            average_confidence=55.0,
            average_edge=1.0,
            status="Pending",
            result="",
        )
        session.add(entry)
        session.flush()
        session.add(EntryPropModel(
            entry_id=entry.id,
            player_name="Backfill Player",
            team="AAA",
            sport="MLB",
            stat="Hits",
            line=0.5,
            direction="Over",
            platform="PrizePicks",
            game="AAA @ BBB",
            game_time="",
        ))
        session.commit()

    result = EntryRepository.backfill_game_times([{
        "sport": "MLB",
        "game": "AAA @ BBB",
        "game_time": "2026-08-17T19:10:00-04:00",
    }], pending_only=True)

    assert result["updated"] == 1
    assert result["repairs"][0]["player"] == "Backfill Player"

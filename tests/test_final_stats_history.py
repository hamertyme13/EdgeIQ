from datetime import datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.repositories.final_stats_repository import _best_matching_row, _deduplicate_history, _entry_prop_history


def test_spurs_provider_abbreviation_matches_saved_entry_game() -> None:
    row = type("FinalRow", (), {
        "game": "OKC@SA", "game_date": "2026-10-20", "status": "played", "actual": 13.0, "id": 1,
    })()

    assert _best_matching_row(
        [row], "OKC @ SAS", "SAS", target_date="2026-10-20", placed_date="2026-10-20",
    ) is row


def test_missouri_state_provider_abbreviation_recovers_unique_placed_day() -> None:
    row = type("FinalRow", (), {
        "game": "MOST@DEL", "game_date": "2026-10-20", "status": "played", "actual": 2.0, "id": 1,
    })()

    assert _best_matching_row([row], "", "MOSU", placed_date="2026-10-20") is row


def test_history_deduplicates_same_game_across_sources() -> None:
    rows = [
        {"game_date": "2026-08-20", "game": "IND @ MIN", "actual": 24, "source": "espn"},
        {"game_date": "2026-08-20", "game": "MIN vs IND", "actual": 24, "source": "entry_ledger"},
        {"game_date": "2026-08-18", "game": "IND @ NYL", "actual": 27, "source": "espn"},
    ]

    result = _deduplicate_history(rows)

    assert len(result) == 2
    assert result[0]["source"] == "espn"


def test_history_preserves_repeat_matchups_on_different_dates() -> None:
    rows = [
        {"game_date": "2026-08-20", "game": "IND @ MIN", "actual": 24},
        {"game_date": "2026-07-20", "game": "MIN @ IND", "actual": 29},
    ]

    assert len(_deduplicate_history(rows)) == 2


def test_settled_entry_history_uses_indexed_exact_name_and_keeps_accent_fallback(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'entry-history.db'}")
    EntryModel.__table__.create(engine)
    EntryPropModel.__table__.create(engine)
    with Session(engine) as session:
        entry = EntryModel(
            platform="PrizePicks", average_confidence=70, average_edge=1,
            status="Settled", settled_at=datetime(2026, 9, 1),
        )
        session.add(entry)
        session.flush()
        session.add(EntryPropModel(
            entry_id=entry.id, player_name="Azurá Stevens", sport="WNBA", stat="Points",
            actual=20, final_source="espn", game="MIN @ NYL",
        ))
        session.commit()
        statements = []

        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert len(_entry_prop_history(session, "Azurá Stevens", "Points", "WNBA", 15)) == 1
            assert len(_entry_prop_history(session, "Azura Stevens", "Points", "WNBA", 15)) == 1
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert not any("lower(entry_props.player_name)" in statement for statement in statements)
        plan = session.execute(text(
            "EXPLAIN QUERY PLAN SELECT id FROM entry_props "
            "WHERE player_name = 'Azurá Stevens' AND sport = 'WNBA' AND stat = 'Points'"
        )).all()
        assert any("ix_entry_props_player_sport_stat" in str(row) for row in plan)

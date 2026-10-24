from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from repository.models.final_player_stat_model import FinalPlayerStatModel
from services.final_stat_candidates import recent_canonical_player_ids
from services.opportunity_enrichment import attach_opportunity_context


def test_recent_name_fallback_matches_accents_within_sport_and_stat(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    FinalPlayerStatModel.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            FinalPlayerStatModel(player="Azurá Stevens", sport="WNBA", stat="Points", game_date="2026-09-01", actual=21),
            FinalPlayerStatModel(player="Azurá Stevens", sport="NBA", stat="Points", game_date="2026-09-02", actual=10),
            FinalPlayerStatModel(player="Other Player", sport="WNBA", stat="Points", game_date="2026-09-03", actual=12),
        ])
        session.commit()
        ids = recent_canonical_player_ids(session, "Azura Stevens", sport="WNBA", stats={"Points"})
        assert len(ids) == 1
        assert session.get(FinalPlayerStatModel, ids[0]).sport == "WNBA"


def test_opportunity_context_uses_indexed_exact_player_before_name_fallback(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'opportunity.db'}")
    FinalPlayerStatModel.__table__.create(engine)
    with Session(engine) as session:
        session.add(FinalPlayerStatModel(
            player="Test Player", sport="WNBA", stat="Minutes", game="A @ B",
            game_date="2026-09-01", actual=31,
        ))
        session.commit()
        history = [{"player": "Test Player", "sport": "WNBA", "stat": "Points", "game": "A @ B", "game_date": "2026-09-01"}]
        statements = []
        from sqlalchemy import event

        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", record)
        try:
            attach_opportunity_context(session, history, None, "Test Player", "WNBA")
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert history[0]["minutes"] == 31
        assert "verified_minutes" not in history[0]
        assert not any("lower(final_player_stats.player)" in statement for statement in statements)


def test_opportunity_context_marks_provider_verified_minutes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'verified-minutes.db'}")
    FinalPlayerStatModel.__table__.create(engine)
    with Session(engine) as session:
        session.add(FinalPlayerStatModel(
            player="Test Player", sport="NBA", stat="Minutes", game="A @ B",
            game_date="2026-10-20", actual=32, source="espn", season_type="regular",
        ))
        session.commit()
        history = [{"player": "Test Player", "sport": "NBA", "stat": "Points", "game": "A @ B", "game_date": "2026-10-20"}]

        attach_opportunity_context(session, history, None, "Test Player", "NBA")

        assert history[0]["minutes"] == 32
        assert history[0]["verified_minutes"] == 32

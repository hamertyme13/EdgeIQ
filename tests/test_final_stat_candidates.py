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


def test_nba_minutes_context_rejects_conflicts_preseason_and_unplayed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'minutes-evidence.db'}")
    FinalPlayerStatModel.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Minutes", game="A @ B",
                                 game_date="2026-10-20", actual=32, source="espn", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Minutes", game="A @ B",
                                 game_date="2026-10-20", actual=34, source="nba_api", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Minutes", game="C @ D",
                                 game_date="2026-10-21", actual=30, source="espn", season_type="preseason"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Minutes", game="E @ F",
                                 game_date="2026-10-22", actual=28, source="espn", season_type="regular", status="dnp"),
        ])
        session.commit()
        history = [
            {"player": "Test Player", "sport": "NBA", "stat": "Points", "game": game, "game_date": day}
            for game, day in (("A @ B", "2026-10-20"), ("C @ D", "2026-10-21"), ("E @ F", "2026-10-22"))
        ]

        attach_opportunity_context(session, history, None, "Test Player", "NBA")

        assert all("verified_minutes" not in row for row in history)


def test_nba_shot_attempt_context_requires_consistent_verified_provider_values(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'verified-shots.db'}")
    FinalPlayerStatModel.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Field Goals Attempted", game="A @ B",
                                 game_date="2026-10-20", actual=16, source="espn", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Field Goals Attempted", game="A @ B",
                                 game_date="2026-10-20", actual=16, source="nba_api", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Free Throws Attempted", game="A @ B",
                                 game_date="2026-10-20", actual=7, source="espn", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Free Throws Attempted", game="A @ B",
                                 game_date="2026-10-20", actual=9, source="statshawk", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Free Throws Attempted", game="A @ B",
                                 game_date="2026-10-20", actual=11, source="manual", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Field Goals Attempted", game="C @ D",
                                 game_date="2026-10-21", actual=18, source="manual", season_type="regular"),
            FinalPlayerStatModel(player="Test Player", sport="NBA", stat="Free Throws Attempted", game="C @ D",
                                 game_date="2026-10-21", actual=8, source="espn", season_type="preseason"),
        ])
        session.commit()
        history = [
            {"player": "Test Player", "sport": "NBA", "stat": "Points", "game": "A @ B", "game_date": "2026-10-20"},
            {"player": "Test Player", "sport": "NBA", "stat": "Points", "game": "C @ D", "game_date": "2026-10-21"},
        ]

        attach_opportunity_context(session, history, None, "Test Player", "NBA")

        assert history[0]["verified_field_goals_attempted"] == 16
        assert "verified_free_throws_attempted" not in history[0]
        assert "verified_field_goals_attempted" not in history[1]
        assert "verified_free_throws_attempted" not in history[1]

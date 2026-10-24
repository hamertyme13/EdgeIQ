from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from repository.database import Base
from repository.models.final_player_stat_model import FinalPlayerStatModel
from services.nba_season_provenance import backfill_nba_season_type


def _event(away, home, *, season="regular-season", completed=True):
    return {
        "season": {"slug": season} if season else {},
        "competitions": [{
            "status": {"type": {"completed": completed}},
            "competitors": [
                {"homeAway": "away", "team": {"abbreviation": away}},
                {"homeAway": "home", "team": {"abbreviation": home}},
            ],
        }],
    }


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'provenance.db'}")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        for game, stat, season_type in [
            ("ATL@ORL", "Points", None),
            ("ATL@ORL", "Assists", None),
            ("BOS@NYK", "Points", None),
            ("CHI@MIA", "Points", "regular"),
        ]:
            session.add(FinalPlayerStatModel(
                player="Test Player", sport="NBA", stat=stat, game=game,
                game_date="2026-10-21", actual=10, season_type=season_type,
            ))
        session.commit()
    return session_local


def test_backfill_previews_then_applies_only_exact_completed_match(tmp_path):
    session_local = _session(tmp_path)
    loader = lambda _: {"events": [_event("ATL", "ORL"), _event("BOS", "NYK", completed=False)]}
    with session_local() as session:
        preview = backfill_nba_season_type(session, today=date(2026, 10, 22), scoreboard_loader=loader)
        assert preview["mode"] == "preview"
        assert preview["matched_games"] == 1
        assert preview["rows"] == 2
    with session_local() as session:
        assert session.query(FinalPlayerStatModel).filter(FinalPlayerStatModel.season_type.is_(None)).count() == 3
        applied = backfill_nba_season_type(session, today=date(2026, 10, 22), apply=True, scoreboard_loader=loader)
        assert applied["rows"] == 2
    with session_local() as session:
        assert session.query(FinalPlayerStatModel).filter(FinalPlayerStatModel.season_type.is_(None)).count() == 1
        assert session.query(FinalPlayerStatModel).filter(FinalPlayerStatModel.season_type == "regular").count() == 3


def test_backfill_skips_ambiguous_and_unlabeled_events(tmp_path):
    session_local = _session(tmp_path)
    loader = lambda _: {"events": [
        _event("ATL", "ORL", season="preseason"),
        _event("ATL", "ORL", season="regular-season"),
        _event("BOS", "NYK", season=None),
    ]}
    with session_local() as session:
        report = backfill_nba_season_type(session, today=date(2026, 10, 22), apply=True, scoreboard_loader=loader)
        assert report["ambiguous_games"] == 1
        assert report["unlabeled_events"] == 1
        assert report["rows"] == 0
    with session_local() as session:
        assert session.query(FinalPlayerStatModel).filter(FinalPlayerStatModel.season_type.is_(None)).count() == 3

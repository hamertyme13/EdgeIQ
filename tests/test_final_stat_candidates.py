from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from repository.models.final_player_stat_model import FinalPlayerStatModel
from services.final_stat_candidates import recent_canonical_player_ids


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

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from repository.database import Base
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.market_quote_snapshot_model import MarketQuoteSnapshotModel
from repository.repositories import market_quote_repository as module


def test_quote_snapshots_are_immutable_and_deduplicated(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'quotes.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "SessionLocal", sessions)
    offer = {
        "player": "Research Guard", "platform": "PrizePicks", "provider_offer_id": "pp-1",
        "provider_event_id": "game-1", "game": "BOS @ NYK", "game_time": "2026-10-23T23:00:00Z",
        "line": 19.5, "line_offer_type": "standard",
    }
    quote = {
        "source": "The Odds API", "source_type": "multi_book_no_vig",
        "event": {"event_id": "odds-1", "commence_time": "2026-10-23T23:00:00Z"},
        "books": [{"bookmaker_key": "book-a", "over_odds": -110, "under_odds": -105}],
        "over_probability": 54.0, "under_probability": 46.0,
        "book_count": 1, "oldest_update": "2026-10-23T15:55:00Z",
    }

    first = module.MarketQuoteRepository.record(offer, quote, 62.0, "points-v1")
    repeated = module.MarketQuoteRepository.record(offer, quote, 62.0, "points-v1")
    changed = module.MarketQuoteRepository.record(
        offer, {**quote, "over_probability": 55.0, "under_probability": 45.0}, 62.0, "points-v1",
    )

    assert first["id"] == repeated["id"]
    assert changed["id"] != first["id"]
    history = module.MarketQuoteRepository.history(
        "Research Guard", "PrizePicks", "BOS @ NYK", "2026-10-23T23:00:00Z", 19.5,
    )
    wrong_game = module.MarketQuoteRepository.history(
        "Research Guard", "PrizePicks", "BOS @ MIA", "2026-10-23T23:00:00Z", 19.5,
    )
    assert [row["market_over_probability"] for row in history] == [54.0, 55.0]
    assert wrong_game == []
    summary = module.MarketQuoteRepository.summary()
    assert summary["collection_mode"] == "on_demand"
    assert summary["payout_verified"] is False
    assert summary["last_captured_at"]
    with sessions() as session:
        rows = session.query(MarketQuoteSnapshotModel).order_by(MarketQuoteSnapshotModel.id).all()
        assert len(rows) == 2
        assert rows[0].market_over_probability == 54.0
        assert rows[1].market_over_probability == 55.0
        assert rows[0].provider_offer_id == "pp-1"
        assert rows[0].model_version == "points-v1"
        session.add(FinalPlayerStatModel(
            player="Research Guard", sport="NBA", stat="Points", game="BOS @ NYK",
            game_date="2026-10-23", season_type="regular", actual=27,
            status="played", source="espn",
        ))
        session.commit()
    inputs = module.MarketQuoteRepository.validation_inputs()
    assert len(inputs["quotes"]) == 2
    assert len(inputs["finals"]) == 1
    assert inputs["quote_limit_reached"] is False
    assert inputs["finals_truncated"] is False

from sqlalchemy import Column, Float, Index, Integer, String, Text

from repository.database import Base


class MarketQuoteSnapshotModel(Base):
    __tablename__ = "market_quote_snapshots"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), nullable=False, unique=True)
    captured_at = Column(String(50), nullable=False)
    player_key = Column(String(200), nullable=False)
    player = Column(String(200), nullable=False)
    platform = Column(String(80), nullable=False)
    provider_offer_id = Column(String(160), nullable=False, default="")
    provider_event_id = Column(String(160), nullable=False, default="")
    game = Column(String(300), nullable=False)
    game_time = Column(String(50), nullable=False)
    line = Column(Float, nullable=False)
    offer_type = Column(String(40), nullable=False)
    market_event_id = Column(String(160), nullable=False)
    oldest_quote_at = Column(String(50), nullable=False)
    book_count = Column(Integer, nullable=False)
    market_over_probability = Column(Float, nullable=False)
    market_under_probability = Column(Float, nullable=False)
    model_over_probability = Column(Float)
    model_version = Column(String(160), nullable=False, default="")
    quote_payload = Column(Text, nullable=False)

    __table_args__ = (
        Index("ix_market_quote_player_game", "player_key", "game_time"),
        Index("ix_market_quote_captured_at", "captured_at"),
    )

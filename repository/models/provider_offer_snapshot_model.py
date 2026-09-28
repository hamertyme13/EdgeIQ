from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text

from repository.database import Base


class ProviderOfferSnapshotModel(Base):
    __tablename__ = "provider_offer_snapshots"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(String(64), nullable=False, unique=True)
    provider = Column(String(80), nullable=False)
    provider_offer_id = Column(String(160), nullable=False, default="")
    provider_player_id = Column(String(160), nullable=False, default="")
    provider_event_id = Column(String(160), nullable=False, default="")
    player_key = Column(String(200), nullable=False)
    sport = Column(String(40), nullable=False)
    game = Column(String(300), nullable=False, default="")
    game_start = Column(String(50), nullable=False, default="")
    stat = Column(String(120), nullable=False)
    allowed_directions = Column(Text, nullable=False)
    line = Column(Float, nullable=False)
    offer_type = Column(String(40), nullable=False)
    standard_line = Column(Float)
    baseline_line = Column(Float)
    discounted = Column(Boolean, nullable=False, default=False)
    premium = Column(Boolean, nullable=False, default=False)
    source = Column(String(120), nullable=False, default="")
    source_hash = Column(String(64), nullable=False, default="")
    first_observed_at = Column(String(50), nullable=False, default="")
    last_observed_at = Column(String(50), nullable=False, default="")
    expires_at = Column(String(50), nullable=False, default="")
    created_at = Column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_provider_offer_snapshot_market", "sport", "player_key", "stat"),
        Index("ix_provider_offer_snapshot_provider_event", "provider", "provider_event_id"),
    )

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class BoardOfferObservationModel(Base):
    """Immutable provider-board observation, including markets EdgeIQ rejected."""

    __tablename__ = "board_offer_observations"

    id = Column(Integer, primary_key=True)
    observation_key = Column(String, nullable=False)
    market_key = Column(String, nullable=False, index=True)
    offer_key = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    provider_offer_id = Column(String, default="", index=True)
    provider_player_id = Column(String, default="", index=True)
    player_identity_id = Column(Integer, index=True)
    normalized_player_key = Column(String, nullable=False, index=True)
    player = Column(String, nullable=False)
    team = Column(String, default="")
    opponent = Column(String, default="")
    sport = Column(String, nullable=False, index=True)
    stat = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)
    line = Column(Float, nullable=False)
    opening_line = Column(Float)
    closing_line = Column(Float)
    offer_type = Column(String, nullable=False, default="standard")
    payout_multiplier = Column(Float)
    game_id = Column(String, default="", index=True)
    game = Column(String, default="")
    scheduled_start = Column(String, default="", index=True)
    home_away = Column(String, default="")
    rest_days = Column(Float)
    projection = Column(Float)
    probability = Column(Float)
    expected_minutes = Column(Float)
    expected_opportunities = Column(Float)
    model_version = Column(String, default="")
    feature_snapshot = Column(Text, default="")
    context_snapshot = Column(Text, default="")
    provider_payload = Column(Text, default="")
    eligibility_status = Column(String, default="unreviewed", index=True)
    eligibility_reason = Column(Text, default="")
    actual = Column(Float)
    outcome = Column(String, default="", index=True)
    outcome_source = Column(String, default="")
    captured_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    analyzed_at = Column(DateTime)
    settled_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("observation_key", name="uq_board_offer_observation_key"),
    )

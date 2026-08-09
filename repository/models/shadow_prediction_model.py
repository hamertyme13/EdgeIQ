from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class ShadowPredictionModel(Base):
    __tablename__ = "shadow_predictions"

    id = Column(Integer, primary_key=True)
    cohort_date = Column(String, nullable=False, index=True)
    model_version = Column(String, nullable=False, index=True)
    independent_market_key = Column(String, nullable=False, index=True)
    player = Column(String, nullable=False)
    team = Column(String, default="")
    sport = Column(String, nullable=False, index=True)
    stat = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)
    platform = Column(String, nullable=False, index=True)
    game = Column(String, default="")
    game_time = Column(String, default="")
    line = Column(Float, nullable=False)
    projection = Column(Float)
    probability = Column(Float, nullable=False)
    feature_snapshot = Column(Text, default="")
    status = Column(String, nullable=False, default="shadow_pending", index=True)
    actual = Column(Float)
    outcome_source = Column(String, default="")
    settlement_attempts = Column(Integer, nullable=False, default=0)
    last_settlement_error = Column(Text, default="")
    predicted_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_attempt_at = Column(DateTime)
    settled_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("cohort_date", "model_version", "independent_market_key", name="uq_shadow_cohort_market"),
    )

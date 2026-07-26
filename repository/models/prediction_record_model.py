from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class PredictionRecordModel(Base):
    __tablename__ = "prediction_records"

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, nullable=False, index=True)
    entry_prop_id = Column(Integer, nullable=False, index=True)
    independent_market_key = Column(String, nullable=False, index=True)
    offer_key = Column(String, nullable=False, index=True)
    player_identity_id = Column(Integer, index=True)
    player = Column(String, nullable=False)
    team = Column(String, default="")
    sport = Column(String, nullable=False, index=True)
    stat = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)
    platform = Column(String, nullable=False, index=True)
    game = Column(String, default="")
    game_time = Column(String, default="")
    line = Column(Float, nullable=False)
    projection = Column(Float, nullable=False)
    probability = Column(Float, nullable=False)
    projection_source = Column(String, default="")
    model_version = Column(String, nullable=False)
    line_offer_type = Column(String, default="standard")
    feature_as_of = Column(String, default="")
    feature_snapshot = Column(Text, default="")
    payout_snapshot = Column(Text, default="")
    legacy_quarantined = Column(Boolean, nullable=False, default=False)
    outcome = Column(String, default="")
    actual = Column(Float)
    outcome_source = Column(String, default="")
    predicted_at = Column(DateTime, server_default=func.now(), nullable=False)
    settled_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("entry_prop_id", name="uq_prediction_record_entry_prop"),
    )

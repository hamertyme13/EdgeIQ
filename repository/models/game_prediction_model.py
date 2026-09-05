from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class GamePredictionModel(Base):
    __tablename__ = "game_predictions"

    id = Column(Integer, primary_key=True)
    prediction_key = Column(String(160), nullable=False, unique=True, index=True)
    sport = Column(String(20), nullable=False, index=True)
    game_id = Column(String(120), nullable=False, index=True)
    game = Column(String(240), nullable=False)
    home_team = Column(String(120), nullable=False)
    away_team = Column(String(120), nullable=False)
    game_start = Column(String(64), default="", index=True)
    model_version = Column(String(120), nullable=False, index=True)
    home_win_probability = Column(Float, nullable=False)
    away_win_probability = Column(Float, nullable=False)
    expected_margin = Column(Float, nullable=False)
    expected_total = Column(Float, nullable=False)
    expected_home_points = Column(Float, nullable=False)
    expected_away_points = Column(Float, nullable=False)
    expected_pace = Column(Float)
    blowout_probability = Column(Float)
    game_script = Column(String(40), default="neutral", index=True)
    game_script_confidence = Column(Float, default=0.0)
    data_quality = Column(String(24), default="Thin", index=True)
    evidence_json = Column(Text, nullable=False, default="{}")
    generated_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    actual_home_win = Column(Float)
    actual_margin = Column(Float)
    actual_total = Column(Float)
    actual_home_points = Column(Float)
    actual_away_points = Column(Float)
    outcome_source = Column(String(120), default="")
    settled_at = Column(DateTime)

    __table_args__ = (UniqueConstraint("prediction_key", name="uq_game_predictions_prediction_key"),)

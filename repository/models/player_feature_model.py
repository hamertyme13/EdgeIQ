from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class PlayerFeatureModel(Base):
    __tablename__ = "player_features"

    id = Column(Integer, primary_key=True)
    feature_key = Column(String, nullable=False, unique=True, index=True)
    player_identity_id = Column(Integer, index=True)
    normalized_player_key = Column(String, nullable=False, index=True)
    player = Column(String, nullable=False)
    team = Column(String, default="")
    sport = Column(String, nullable=False, index=True)
    stat = Column(String, nullable=False, index=True)
    sample_size = Column(Integer, default=0)
    history_json = Column(Text, default="[]")
    summary_json = Column(Text, default="{}")
    source_updated_at = Column(String, default="")
    materialized_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("normalized_player_key", "sport", "stat", name="uq_player_feature_segment"),
    )

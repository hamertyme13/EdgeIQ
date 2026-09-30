from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from repository.database import Base


class LegRecommendationSnapshotModel(Base):
    __tablename__ = "leg_recommendation_snapshots"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(String(64), unique=True, nullable=False, index=True)
    feed_snapshot_id = Column(String, nullable=False, index=True)
    offer_snapshot_id = Column(String(64), nullable=False, index=True)
    model_version = Column(String, nullable=False)
    player = Column(String, nullable=False)
    sport = Column(String, nullable=False)
    stat = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(Float, nullable=False)
    projection = Column(Float)
    confidence = Column(Float)
    feature_as_of = Column(String, nullable=False, default="")
    evidence = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

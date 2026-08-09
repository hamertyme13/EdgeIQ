from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class RecommendationSnapshotModel(Base):
    __tablename__ = "recommendation_snapshots"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(String, nullable=False, unique=True, index=True)
    model_version = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=False, index=True)
    sport = Column(String, nullable=False, index=True)
    purpose = Column(String, nullable=False, index=True)
    captured_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    payload = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_recommendation_snapshot_id"),
    )

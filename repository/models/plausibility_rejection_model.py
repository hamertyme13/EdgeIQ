from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class PlausibilityRejectionModel(Base):
    __tablename__ = "plausibility_rejections"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String, nullable=False, unique=True, index=True)
    rejection_reason = Column(Text, nullable=False)
    original_provider_payload = Column(Text, nullable=False)
    provider = Column(String, nullable=False, default="unknown", index=True)
    rejected_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    last_seen_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    normalized_value = Column(String, nullable=False, default="")
    expected_minimum = Column(Float)
    expected_maximum = Column(Float)
    sport = Column(String, nullable=False, default="", index=True)
    stat = Column(String, nullable=False, default="", index=True)
    occurrence_count = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_plausibility_rejection_fingerprint"),
    )

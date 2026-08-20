from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class ResearchEvidenceModel(Base):
    __tablename__ = "research_evidence"

    id = Column(Integer, primary_key=True)
    evidence_id = Column(String, nullable=False, unique=True, index=True)
    fingerprint = Column(String, nullable=False, unique=True, index=True)
    player_key = Column(String, default="", index=True)
    player = Column(String, default="", index=True)
    sport = Column(String, default="", index=True)
    stat = Column(String, default="", index=True)
    platform = Column(String, default="", index=True)
    game_key = Column(String, default="", index=True)
    game = Column(String, default="")
    evidence_type = Column(String, nullable=False, index=True)
    source_name = Column(String, nullable=False, index=True)
    source_url = Column(String, default="")
    source_kind = Column(String, default="api")
    captured_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_accessed_at = Column(DateTime, server_default=func.now(), nullable=False)
    payload = Column(Text, nullable=False)
    use_count = Column(Integer, nullable=False, default=0)
    win_count = Column(Integer, nullable=False, default=0)
    loss_count = Column(Integer, nullable=False, default=0)
    push_count = Column(Integer, nullable=False, default=0)
    usefulness_score = Column(Float, nullable=False, default=0.0)
    outcome_keys = Column(Text, nullable=False, default="[]")

    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_research_evidence_id"),
        UniqueConstraint("fingerprint", name="uq_research_evidence_fingerprint"),
    )

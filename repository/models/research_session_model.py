from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from repository.database import Base


class ResearchSessionModel(Base):
    __tablename__ = "research_sessions"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String, nullable=False, unique=True, index=True)
    player = Column(String, nullable=False, index=True)
    sport = Column(String, nullable=False, default="", index=True)
    stat = Column(String, nullable=False, default="", index=True)
    platform = Column(String, nullable=False, default="")
    line = Column(Float, nullable=True)
    summary_json = Column(Text, nullable=False, default="{}")
    run_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

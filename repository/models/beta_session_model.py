from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from repository.database import Base


class BetaSessionModel(Base):
    __tablename__ = "beta_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("beta_users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    last_active_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    ended_at = Column(DateTime, index=True)

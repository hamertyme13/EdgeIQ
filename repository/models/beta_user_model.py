from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from repository.database import Base


class BetaUserModel(Base):
    __tablename__ = "beta_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    username = Column(String(80), nullable=False, unique=True, index=True)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(24), nullable=False, default="BETA_TESTER", index=True)
    is_beta_tester = Column(Boolean, nullable=False, default=True, index=True)
    beta_cohort = Column(String(40), nullable=False, default="FOUNDING_25", index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    onboarding_completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    last_active_at = Column(DateTime, index=True)

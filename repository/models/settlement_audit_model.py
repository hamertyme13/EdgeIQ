from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class SettlementAuditModel(Base):
    __tablename__ = "settlement_audits"

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, nullable=False, index=True)
    entry_prop_id = Column(Integer, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, default="")
    matched_identity_id = Column(Integer)
    requested_player = Column(String, nullable=False, default="")
    matched_player = Column(String, nullable=False, default="")
    requested_game = Column(String, nullable=False, default="")
    matched_game = Column(String, nullable=False, default="")
    actual = Column(Float)
    result = Column(String, nullable=False, default="")
    reason_code = Column(String, nullable=False, default="", index=True)
    message = Column(String, nullable=False, default="")
    details = Column(Text, nullable=False, default="")
    attempt_count = Column(Integer, nullable=False, default=1)
    attempted_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("entry_prop_id", "status", "provider", "reason_code", name="uq_settlement_audit_attempt"),
    )

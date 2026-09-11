from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from repository.database import Base


class BetaIssueModel(Base):
    __tablename__ = "beta_issues"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("beta_users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("beta_sessions.id"), index=True)
    prediction_record_id = Column(Integer, ForeignKey("prediction_records.id"), index=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), index=True)
    entry_prop_id = Column(Integer, ForeignKey("entry_props.id"), index=True)
    issue_type = Column(String(24), nullable=False, index=True)
    category = Column(String(80), nullable=False, default="Other", index=True)
    description = Column(Text, nullable=False)
    normalized_key = Column(String(160), nullable=False, default="", index=True)
    status = Column(String(24), nullable=False, default="OPEN", index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

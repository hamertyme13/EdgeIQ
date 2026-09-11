from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from repository.database import Base


class BetaFeedbackModel(Base):
    __tablename__ = "beta_feedback"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("beta_users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("beta_sessions.id"), index=True)
    prediction_record_id = Column(Integer, ForeignKey("prediction_records.id"), index=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), index=True)
    entry_prop_id = Column(Integer, ForeignKey("entry_props.id"), index=True)
    useful = Column(Boolean)
    changed_decision = Column(Boolean, nullable=False, default=False, index=True)
    initial_pick = Column(String(16), nullable=False, default="Unsure")
    final_pick = Column(String(16), nullable=False, default="Pass")
    would_pick = Column(String(16), nullable=False, default="Unsure")
    would_pay = Column(String(32), nullable=False, default="")
    feedback_text = Column(Text, nullable=False, default="")
    context_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "prediction_record_id",
            "entry_prop_id",
            name="uq_beta_feedback_user_context",
        ),
    )

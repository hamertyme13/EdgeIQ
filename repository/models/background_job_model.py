from sqlalchemy import Boolean, Column, Integer, String, Text

from repository.database import Base


class BackgroundJobModel(Base):
    __tablename__ = "background_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String, nullable=False, unique=True, index=True)
    kind = Column(String, nullable=False, index=True)
    label = Column(String, default="")
    dedupe_key = Column(String, default="", index=True)
    status = Column(String, nullable=False, index=True)
    progress = Column(Integer, default=0)
    phase = Column(Text, default="")
    created_at = Column(String, default="", index=True)
    started_at = Column(String, default="")
    completed_at = Column(String, default="")
    cancel_requested = Column(Boolean, default=False)
    result_json = Column(Text, default="{}")
    error = Column(Text, default="")
    owner_id = Column(String, default="", index=True)
    process_id = Column(Integer, default=0)
    heartbeat_at = Column(String, default="", index=True)

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from repository.database import Base


class ProductEventModel(Base):
    __tablename__ = "product_events"

    id = Column(Integer, primary_key=True)
    event_name = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, default="", index=True)
    entity_id = Column(String, nullable=False, default="", index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

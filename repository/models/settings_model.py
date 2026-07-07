from sqlalchemy import Column, String

from repository.database import Base


class SettingsModel(Base):

    __tablename__ = "settings"

    key   = Column(String, primary_key=True)
    value = Column(String, nullable=False)

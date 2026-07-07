import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")

engine = create_engine(
    DATABASE_URL,
    echo=False
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


def initialize_database():

    from repository.models.entry_model import EntryModel
    from repository.models.entry_prop_model import EntryPropModel
    
    Base.metadata.create_all(bind=engine)

    
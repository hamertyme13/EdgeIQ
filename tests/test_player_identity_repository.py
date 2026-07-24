from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.player_identity_repository as identity_module
from repository.database import Base
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.repositories.player_identity_repository import PlayerIdentityRepository


def test_identity_registry_matches_accents_and_keeps_name_only_aliases_distinct(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(identity_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)

    plain = PlayerIdentityRepository.resolve("Azura Stevens", "WNBA", "LAS")
    accented = PlayerIdentityRepository.resolve("Azurá Stevens", "WNBA", "LAS", "ESPN", "4433408")
    other = PlayerIdentityRepository.resolve("Alyssa Thomas", "WNBA", "PHX")

    assert plain["id"] == accented["id"]
    assert accented["provider_player_id"] == "4433408"
    assert other["id"] != plain["id"]

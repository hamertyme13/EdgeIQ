from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.player_identity_repository as identity_module
from repository.database import Base
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.models.player_identity_model import PlayerAliasModel, PlayerIdentityModel
from repository.repositories.player_identity_repository import PlayerIdentityRepository
from web.routers.players import player_directory


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
    assert [row["canonical_name"] if "canonical_name" in row else row["name"] for row in PlayerIdentityRepository.search("WNBA", "azura")] == ["Azura Stevens"]
    assert PlayerIdentityRepository.search("NFL", "azura") == []
    assert player_directory("WNBA", "stevens", 10)["players"][0]["id"] == plain["id"]


def test_provider_player_capture_recovers_from_concurrent_identity_insert(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'identities.db'}")
    session_local = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(identity_module, "SessionLocal", session_local)
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)
    rows = [{
        "player": "Arch Manning",
        "sport": "NCAAF",
        "team": "TEX",
        "provider_player_id": "253881",
    }]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _index: PlayerIdentityRepository.capture_provider_players(rows, "PrizePicks"),
            range(2),
        ))

    assert all(result["identity_ids"][("NCAAF", "archmanning")] for result in results)
    with session_local() as session:
        assert session.query(PlayerIdentityModel).count() == 1
        assert session.query(PlayerAliasModel).count() == 1


def test_provider_player_capture_excludes_multi_player_combo_markets(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'combo-identities.db'}")
    session_local = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(identity_module, "SessionLocal", session_local)
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)

    result = PlayerIdentityRepository.capture_provider_players([
        {"player": "Arch Manning", "sport": "NCAAF", "team": "TEX", "provider_player_id": "1"},
        {"player": "Raleek Brown + Arch Manning", "sport": "NCAAF", "team": "TEX", "provider_player_id": "2"},
    ], "PrizePicks")

    assert result["players"] == 1
    assert [row["name"] for row in PlayerIdentityRepository.search("NCAAF", "Arch")] == ["Arch Manning"]

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.player_identity_repository as identity_module
from repository.database import Base
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.models.final_player_stat_model import FinalPlayerStatModel
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


def test_read_only_resolution_does_not_replace_current_team(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(identity_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)

    PlayerIdentityRepository.resolve("Research Guard", "NBA", "PHI")
    looked_up = PlayerIdentityRepository.resolve("Research Guard", "NBA", "BOS", "ESPN", "old-id", create=False)

    assert looked_up["team"] == "PHI"
    assert PlayerIdentityRepository.search("NBA", "Research Guard")[0]["team"] == "PHI"
    assert PlayerIdentityRepository.aliases(looked_up["id"]) == [{
        "provider": "", "provider_player_id": "", "name": "Research Guard", "sport": "NBA", "team": "PHI",
    }]


def test_directory_hides_invalid_team_values_and_provider_capture_cannot_replace_roster(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(identity_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)

    PlayerIdentityRepository.resolve("Aja Wilson", "WNBA", "LVA")
    PlayerIdentityRepository.capture_provider_players([{"player": "Aja Wilson", "sport": "WNBA", "team": "Aja Wilson"}], "PrizePicks")
    assert PlayerIdentityRepository.search("WNBA", "Aja Wilson")[0]["team"] == "LVA"

    with identity_module.SessionLocal() as session:
        row = session.query(PlayerIdentityModel).filter_by(canonical_name="Aja Wilson").one()
        row.current_team = "bd252434-828d-48d8-9884-6b0c7dd1b910"
        session.add(FinalPlayerStatModel(
            player="Aja Wilson", player_identity_id=row.id, team="LVA", sport="WNBA",
            stat="Points", game_date="2026-10-09", actual=25, status="played", source="espn",
        ))
        session.commit()
    player = PlayerIdentityRepository.search("WNBA", "Aja Wilson")[0]
    assert player["team"] == ""
    assert (player["last_verified_team"], player["last_verified_team_date"]) == ("LVA", "2026-10-09")


def test_reused_provider_id_does_not_merge_two_players(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(identity_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)

    first = PlayerIdentityRepository.resolve("Guard One", "WNBA", "LVA", "Provider", "shared-id")
    second = PlayerIdentityRepository.resolve("Guard Two", "WNBA", "NYL", "Provider", "shared-id")
    assert first["id"] != second["id"]
    assert PlayerIdentityRepository.search("WNBA", "Guard One")[0]["team"] == "LVA"
    assert PlayerIdentityRepository.search("WNBA", "Guard Two")[0]["team"] == "NYL"

    PlayerIdentityRepository.capture_provider_players([
        {"player": "Guard One", "sport": "WNBA", "team": "LVA", "provider_player_id": "same-team-id"},
        {"player": "Guard Two", "sport": "WNBA", "team": "NYL", "provider_player_id": "same-team-id"},
    ], "Another Provider")
    assert PlayerIdentityRepository.search("WNBA", "Guard One")[0]["id"] == first["id"]
    assert PlayerIdentityRepository.search("WNBA", "Guard Two")[0]["id"] == second["id"]


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

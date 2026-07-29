from __future__ import annotations

from repository.database import SessionLocal, initialize_database
from repository.models.entry_prop_model import EntryPropModel
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.player_identity_model import PlayerAliasModel, PlayerIdentityModel
from utils.entity_normalization import canonical_person_key


class PlayerIdentityRepository:
    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if PlayerIdentityRepository._schema_ready:
            return
        initialize_database()
        PlayerIdentityRepository._schema_ready = True

    @staticmethod
    def resolve(
        player: object,
        sport: object = "",
        team: object = "",
        provider: object = "",
        provider_player_id: object = "",
        create: bool = True,
    ) -> dict | None:
        PlayerIdentityRepository._ensure_schema()
        name = str(player or "").strip()
        key = canonical_person_key(name)
        sport_text = str(sport or "").strip().upper()
        team_text = str(team or "").strip().upper()
        provider_text = _provider_key(provider)
        provider_id = str(provider_player_id or "").strip() or None
        if not key:
            return None

        with SessionLocal() as session:
            alias = None
            if provider_text and provider_id:
                alias = (
                    session.query(PlayerAliasModel)
                    .filter_by(provider=provider_text, provider_player_id=provider_id)
                    .first()
                )
            if alias is None:
                aliases = (
                    session.query(PlayerAliasModel)
                    .filter_by(alias_key=key, sport=sport_text)
                    .all()
                )
                identity_ids = {row.identity_id for row in aliases}
                alias = aliases[0] if len(identity_ids) == 1 and aliases else None

            identity = session.get(PlayerIdentityModel, alias.identity_id) if alias else None
            if identity is None:
                identity = (
                    session.query(PlayerIdentityModel)
                    .filter_by(canonical_key=key, sport=sport_text)
                    .first()
                )
            if identity is None and not create:
                return None
            if identity is None:
                identity = PlayerIdentityModel(
                    canonical_name=name,
                    canonical_key=key,
                    sport=sport_text,
                    current_team=team_text,
                )
                session.add(identity)
                session.flush()
            elif team_text:
                identity.current_team = team_text

            PlayerIdentityRepository._upsert_alias(
                session,
                identity,
                name,
                key,
                sport_text,
                team_text,
                provider_text,
                provider_id,
            )
            session.commit()
            return _identity_dict(identity, provider_text, provider_id, name)

    @staticmethod
    def aliases(identity_id: int) -> list[dict]:
        PlayerIdentityRepository._ensure_schema()
        with SessionLocal() as session:
            rows = (
                session.query(PlayerAliasModel)
                .filter_by(identity_id=identity_id)
                .order_by(PlayerAliasModel.provider.asc(), PlayerAliasModel.alias_name.asc())
                .all()
            )
            return [
                {
                    "provider": row.provider,
                    "provider_player_id": row.provider_player_id or "",
                    "name": row.alias_name,
                    "sport": row.sport,
                    "team": row.team,
                }
                for row in rows
            ]

    @staticmethod
    def backfill_existing() -> dict:
        PlayerIdentityRepository._ensure_schema()
        linked_props = 0
        linked_stats = 0
        with SessionLocal() as session:
            props = session.query(EntryPropModel).all()
            stats = session.query(FinalPlayerStatModel).all()

        for row in props:
            identity = PlayerIdentityRepository.resolve(
                row.player_name,
                row.sport,
                row.team,
                getattr(row, "player_provider", "") or getattr(row, "platform", ""),
                getattr(row, "provider_player_id", ""),
            )
            if identity and getattr(row, "player_identity_id", None) != identity["id"]:
                with SessionLocal() as session:
                    stored = session.get(EntryPropModel, row.id)
                    if stored:
                        stored.player_identity_id = identity["id"]
                        session.commit()
                        linked_props += 1

        for row in stats:
            identity = PlayerIdentityRepository.resolve(
                row.player,
                row.sport,
                row.team,
                getattr(row, "player_provider", "") or getattr(row, "source", ""),
                getattr(row, "provider_player_id", ""),
            )
            if identity and getattr(row, "player_identity_id", None) != identity["id"]:
                with SessionLocal() as session:
                    stored = session.get(FinalPlayerStatModel, row.id)
                    if stored:
                        stored.player_identity_id = identity["id"]
                        session.commit()
                        linked_stats += 1
        return {"entry_props": linked_props, "final_stats": linked_stats}

    @staticmethod
    def _upsert_alias(session, identity, name, key, sport, team, provider, provider_id) -> None:
        query = session.query(PlayerAliasModel).filter_by(identity_id=identity.id, provider=provider, alias_key=key)
        alias = query.first()
        if alias is None and provider and provider_id:
            alias = session.query(PlayerAliasModel).filter_by(provider=provider, provider_player_id=provider_id).first()
        if alias is None:
            alias = PlayerAliasModel(
                identity_id=identity.id,
                provider=provider,
                provider_player_id=provider_id,
                alias_name=name,
                alias_key=key,
                sport=sport,
                team=team,
            )
            session.add(alias)
        else:
            alias.identity_id = identity.id
            alias.alias_name = name
            alias.alias_key = key
            alias.sport = sport
            alias.team = team
            if provider_id:
                alias.provider_player_id = provider_id


def _provider_key(value: object) -> str:
    return canonical_person_key(value)


def _identity_dict(identity, provider: str, provider_id: str | None, observed_name: str) -> dict:
    return {
        "id": identity.id,
        "canonical_name": identity.canonical_name,
        "canonical_key": identity.canonical_key,
        "sport": identity.sport,
        "team": identity.current_team,
        "provider": provider,
        "provider_player_id": provider_id or "",
        "observed_name": observed_name,
    }

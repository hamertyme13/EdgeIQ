from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from repository.database import SessionLocal, initialize_database
from repository.models.board_offer_observation_model import BoardOfferObservationModel
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
    def search(sport: object, query: object = "", limit: int = 100) -> list[dict]:
        PlayerIdentityRepository._ensure_schema()
        sport_text = str(sport or "").strip().upper()
        if not sport_text:
            return []
        query_key = canonical_person_key(query)
        with SessionLocal() as session:
            lookup = session.query(PlayerIdentityModel).filter(
                PlayerIdentityModel.sport == sport_text,
                ~PlayerIdentityModel.canonical_name.contains(" + "),
            )
            if query_key:
                lookup = lookup.filter(PlayerIdentityModel.canonical_key.contains(query_key))
            resolved_limit = max(1, min(int(limit), 250))
            rows = lookup.order_by(PlayerIdentityModel.canonical_name.asc()).limit(resolved_limit).all()
            identity_ids = [identity.id for identity in rows]
            alias_rows = (
                session.query(PlayerAliasModel)
                .filter(PlayerAliasModel.identity_id.in_(identity_ids))
                .order_by(PlayerAliasModel.last_seen_at.desc())
                .all()
                if identity_ids else []
            )
            aliases_by_identity: dict[int, list[dict]] = {}
            for alias in alias_rows:
                aliases_by_identity.setdefault(alias.identity_id, []).append({
                    "provider": alias.provider,
                    "provider_player_id": alias.provider_player_id or "",
                    "name": alias.alias_name,
                })
            players = [
                {
                    "id": identity.id,
                    "name": identity.canonical_name,
                    "sport": identity.sport,
                    "team": identity.current_team,
                    "source": "verified_history",
                    "provider": "",
                    "provider_player_id": "",
                    "provider_aliases": aliases_by_identity.get(identity.id, []),
                }
                for identity in rows
            ]
            seen = {canonical_person_key(row["name"]) for row in players}
            board_lookup = session.query(BoardOfferObservationModel)
            if query_key:
                board_lookup = board_lookup.filter(
                    BoardOfferObservationModel.normalized_player_key.op("GLOB")(f"{query_key}*"),
                )
            else:
                board_lookup = board_lookup.filter(BoardOfferObservationModel.sport == sport_text)
            board_rows = board_lookup.limit(
                resolved_limit * 4,
            ).all()
            for row in board_rows:
                if row.sport != sport_text:
                    continue
                if not _is_individual_player_name(row.player):
                    continue
                key = canonical_person_key(row.player)
                if not key or key in seen:
                    continue
                seen.add(key)
                players.append({
                    "id": None,
                    "name": row.player,
                    "sport": row.sport,
                    "team": row.team,
                    "source": "current_provider_board",
                    "provider": row.provider,
                    "provider_player_id": row.provider_player_id or "",
                    "provider_aliases": [{
                        "provider": _provider_key(row.provider),
                        "provider_player_id": row.provider_player_id or "",
                        "name": row.player,
                    }],
                })
                if len(players) >= resolved_limit:
                    break
            players.sort(key=lambda row: str(row["name"]).lower())
            return players[:resolved_limit]

    @staticmethod
    def capture_provider_players(rows: list[dict], provider: object) -> dict:
        """Materialize provider-board identities in one transaction."""
        PlayerIdentityRepository._ensure_schema()
        return PlayerIdentityRepository._capture_provider_players(rows, provider, retry_on_conflict=True)

    @staticmethod
    def _capture_provider_players(rows: list[dict], provider: object, *, retry_on_conflict: bool) -> dict:
        provider_text = _provider_key(provider)
        prepared: dict[tuple[str, str], dict] = {}
        for row in rows:
            name = str(row.get("player") or "").strip()
            sport = str(row.get("sport") or row.get("league") or "").strip().upper()
            key = canonical_person_key(name)
            if name and sport and key and _is_individual_player_name(name):
                prepared[(sport, key)] = {
                    "name": name,
                    "sport": sport,
                    "key": key,
                    "team": str(row.get("team") or "").strip().upper(),
                    "provider_id": str(row.get("provider_player_id") or row.get("player_id") or "").strip() or None,
                }
        if not prepared:
            return {"players": 0, "aliases": 0, "identity_ids": {}}

        try:
            with SessionLocal() as session:
                sports = {item["sport"] for item in prepared.values()}
                keys = {item["key"] for item in prepared.values()}
                identities = session.query(PlayerIdentityModel).filter(
                    PlayerIdentityModel.sport.in_(sports),
                    PlayerIdentityModel.canonical_key.in_(keys),
                ).all()
                identity_by_key = {(row.sport, row.canonical_key): row for row in identities}
                provider_ids = {item["provider_id"] for item in prepared.values() if item["provider_id"]}
                aliases = session.query(PlayerAliasModel).filter(
                    (PlayerAliasModel.provider == provider_text),
                    (PlayerAliasModel.alias_key.in_(keys)) | (PlayerAliasModel.provider_player_id.in_(provider_ids)),
                ).all()
                alias_by_name = {(row.sport, row.alias_key): row for row in aliases}
                alias_by_provider_id = {row.provider_player_id: row for row in aliases if row.provider_player_id}
                created_players = 0
                created_aliases = 0
                for identity_key, item in prepared.items():
                    alias = alias_by_provider_id.get(item["provider_id"]) if item["provider_id"] else None
                    identity = session.get(PlayerIdentityModel, alias.identity_id) if alias else identity_by_key.get(identity_key)
                    if identity is None:
                        identity = PlayerIdentityModel(
                            canonical_name=item["name"],
                            canonical_key=item["key"],
                            sport=item["sport"],
                            current_team=item["team"],
                        )
                        session.add(identity)
                        session.flush()
                        identity_by_key[identity_key] = identity
                        created_players += 1
                    elif item["team"]:
                        identity.current_team = item["team"]
                    identity_by_key[identity_key] = identity
                    alias = alias or alias_by_name.get(identity_key)
                    if alias is None:
                        alias = PlayerAliasModel(
                            identity_id=identity.id,
                            provider=provider_text,
                            provider_player_id=item["provider_id"],
                            alias_name=item["name"],
                            alias_key=item["key"],
                            sport=item["sport"],
                            team=item["team"],
                        )
                        session.add(alias)
                        alias_by_name[identity_key] = alias
                        if item["provider_id"]:
                            alias_by_provider_id[item["provider_id"]] = alias
                        created_aliases += 1
                    else:
                        alias.identity_id = identity.id
                        alias.alias_name = item["name"]
                        alias.team = item["team"]
                        if item["provider_id"]:
                            alias.provider_player_id = item["provider_id"]
                session.commit()
                return {
                    "players": created_players,
                    "aliases": created_aliases,
                    "identity_ids": {key: row.id for key, row in identity_by_key.items()},
                }
        except IntegrityError:
            if not retry_on_conflict:
                raise
            return PlayerIdentityRepository._capture_provider_players(rows, provider, retry_on_conflict=False)

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


def _is_individual_player_name(value: object) -> bool:
    return bool(str(value or "").strip()) and " + " not in str(value)


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

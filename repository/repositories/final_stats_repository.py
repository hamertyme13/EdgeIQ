from __future__ import annotations

from datetime import date, datetime
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.repositories.player_identity_repository import PlayerIdentityRepository
from services.opportunity_enrichment import attach_opportunity_context
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import canonical_stat_label, stat_alias_labels


class FinalStatsRepository:

    @staticmethod
    def upsert_many(rows: list[dict]) -> int:
        saved = 0
        prepared = []
        identity_cache: dict[tuple[str, str, str, str, str], dict | None] = {}
        for row in rows:
            normalized = _normalize_row(row)
            if normalized is None:
                continue
            identity_key = (
                canonical_person_key(normalized["player"]),
                normalized["sport"],
                normalized["team"],
                normalized["player_provider"] or normalized["source"],
                normalized["provider_player_id"],
            )
            if identity_key not in identity_cache:
                identity_cache[identity_key] = PlayerIdentityRepository.resolve(
                    normalized["player"],
                    normalized["sport"],
                    normalized["team"],
                    normalized["player_provider"] or normalized["source"],
                    normalized["provider_player_id"],
                )
            identity = identity_cache[identity_key]
            normalized["player_identity_id"] = identity["id"] if identity else None
            prepared.append(normalized)
        if not prepared:
            return 0
        with SessionLocal() as session:
            existing_index: dict[tuple[str, str, str, str, str], FinalPlayerStatModel] = {}
            existing_rows = (
                session.query(FinalPlayerStatModel)
                .filter(FinalPlayerStatModel.sport.in_({row["sport"] for row in prepared}))
                .filter(FinalPlayerStatModel.stat.in_({row["stat"] for row in prepared}))
                .filter(FinalPlayerStatModel.game_date.in_({row["game_date"] for row in prepared}))
                .order_by(FinalPlayerStatModel.id.desc())
                .all()
            )
            for row in existing_rows:
                key = (
                    row.sport,
                    row.stat,
                    str(row.game_date or ""),
                    canonical_person_key(row.player),
                    _game_key(row.game),
                )
                existing_index.setdefault(key, row)
            for normalized in prepared:
                key = (
                    normalized["sport"],
                    normalized["stat"],
                    normalized["game_date"],
                    canonical_person_key(normalized["player"]),
                    _game_key(normalized["game"]),
                )
                existing = existing_index.get(key)
                if existing:
                    incoming_is_live = normalized["status"] == "live"
                    existing_is_final = (existing.status or "played") in {"played", "dnp"}
                    if not (incoming_is_live and existing_is_final):
                        existing.actual = normalized["actual"]
                        existing.team = normalized["team"]
                        existing.status = normalized["status"]
                        existing.source = normalized["source"]
                        existing.player_identity_id = normalized["player_identity_id"]
                        existing.player_provider = normalized["player_provider"]
                        existing.provider_player_id = normalized["provider_player_id"]
                else:
                    existing = FinalPlayerStatModel(**normalized)
                    session.add(existing)
                    session.flush()
                    existing_index[key] = existing
                saved += 1
            # Imported locally because the feature repository reads this
            # repository while rebuilding a segment.
            from repository.repositories.player_feature_repository import PlayerFeatureRepository

            PlayerFeatureRepository.expire_segments(session, prepared)
            session.commit()
        return saved

    @staticmethod
    def find_actual(prop: dict) -> float | None:
        row = FinalStatsRepository.find_result(prop)
        if row is None or row.get("status") != "played":
            return None
        return row["actual"]

    @staticmethod
    def find_result(prop: dict) -> dict | None:
        try:
            with SessionLocal() as session:
                excluded_sources = [
                    str(source).strip().lower()
                    for source in prop.get("_excluded_sources", [])
                    if str(source).strip()
                ]
                query = (
                    session.query(FinalPlayerStatModel)
                    .filter(FinalPlayerStatModel.sport == prop.get("sport", ""))
                    .filter(FinalPlayerStatModel.stat.in_(stat_alias_labels(prop.get("stat", ""))))
                )
                identity = PlayerIdentityRepository.resolve(
                    prop.get("player", ""),
                    prop.get("sport", ""),
                    prop.get("team", ""),
                    prop.get("player_provider") or prop.get("platform") or "",
                    prop.get("provider_player_id", ""),
                    create=False,
                )
                identity_id = prop.get("player_identity_id") or (identity or {}).get("id")
                if identity_id:
                    query = query.filter(FinalPlayerStatModel.player_identity_id == identity_id)
                else:
                    query = query.filter(FinalPlayerStatModel.player == prop.get("player", ""))
                if excluded_sources:
                    query = query.filter(~FinalPlayerStatModel.source.in_(excluded_sources))
                game = prop.get("game", "")
                target_date = _prop_game_date(prop)
                placed_date = _prop_placed_date(prop)
                rows = query.order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc()).limit(50).all()
                row = _best_matching_row(
                    rows,
                    game,
                    prop.get("team", ""),
                    target_date=target_date,
                    placed_date=placed_date,
                    allow_unique_date_fallback=bool(identity_id),
                )
                if row is None:
                    row = _best_fuzzy_player_row(session, prop)
                if row is None:
                    return None
                return {
                    "actual": row.actual,
                    "status": row.status or "played",
                    "source": row.source,
                    "game": row.game,
                    "game_date": row.game_date,
                    "player": row.player,
                    "player_identity_id": getattr(row, "player_identity_id", None),
                }
        except SQLAlchemyError:
            return None

    @staticmethod
    def history(
        player: str,
        stat: str,
        sport: str | None = None,
        limit: int = 100,
        team: str = "",
        *,
        include_opportunity_context: bool = True,
    ) -> list[dict]:
        try:
            identity = PlayerIdentityRepository.resolve(player, sport or "", create=False)
            with SessionLocal() as session:
                query = (
                    session.query(FinalPlayerStatModel)
                    .filter(FinalPlayerStatModel.stat.in_(stat_alias_labels(stat)))
                )
                if identity:
                    query = query.filter(FinalPlayerStatModel.player_identity_id == identity["id"])
                else:
                    player_key = canonical_person_key(player)
                    candidate_ids = [
                        row.id
                        for row in session.query(FinalPlayerStatModel.id)
                        .filter(FinalPlayerStatModel.player == str(player).strip())
                        .all()
                    ]
                    if not candidate_ids:
                        candidate_ids = [
                            row.id
                            for row in session.query(FinalPlayerStatModel.id).filter(
                                func.lower(FinalPlayerStatModel.player) == str(player).strip().lower()
                            ).all()
                        ]
                    if not candidate_ids:
                        candidate_ids = [
                            row.id
                            for row in session.query(FinalPlayerStatModel.id, FinalPlayerStatModel.player).all()
                            if canonical_person_key(row.player) == player_key
                        ]
                    if not candidate_ids:
                        return []
                    query = query.filter(FinalPlayerStatModel.id.in_(candidate_ids))
                if sport:
                    query = query.filter(FinalPlayerStatModel.sport == sport.upper())
                rows = (
                    query.order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc())
                    .limit(max(limit * 3, limit))
                    .all()
                )
                history = [
                    {
                        "player": row.player,
                        "team": row.team,
                        "sport": row.sport,
                        "stat": row.stat,
                        "game": row.game,
                        "game_date": row.game_date,
                        "actual": row.actual,
                        "status": row.status or "played",
                        "source": row.source,
                    }
                    for row in rows
                ]
                if include_opportunity_context:
                    attach_opportunity_context(session, history, identity, player, sport, team)
                entry_history = _entry_prop_history(session, player, stat, sport, limit)
                return _deduplicate_history(history + entry_history)[:limit]
        except SQLAlchemyError:
            return []


def _deduplicate_history(rows: list[dict]) -> list[dict]:
    """Keep one independent final outcome for each player game and stat."""
    unique: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        game_date = str(row.get("game_date") or "").strip()[:10]
        matchup = _game_key(row.get("game"))
        if game_date or matchup:
            key = (game_date, matchup)
            if key in seen:
                continue
            seen.add(key)
        unique.append(row)
    return unique

def _normalize_row(row: dict) -> dict | None:
    try:
        actual = float(row["actual"])
    except (KeyError, TypeError, ValueError):
        return None

    player = str(row.get("player", "")).strip()
    sport = str(row.get("sport", "")).strip().upper()
    stat = canonical_stat_label(row.get("stat", ""))
    if not player or not sport or not stat:
        return None

    return {
        "player": player,
        "team": str(row.get("team", "")).strip(),
        "sport": sport,
        "stat": stat,
        "game": str(row.get("game", "")).strip(),
        "game_date": str(row.get("game_date", row.get("date", ""))).strip(),
        "actual": actual,
        "status": _normalize_status(row.get("status", "played")),
        "source": str(row.get("source", "import")).strip() or "import",
        "player_provider": str(row.get("player_provider") or row.get("provider") or row.get("source") or "").strip(),
        "provider_player_id": str(row.get("provider_player_id") or row.get("player_id") or "").strip(),
    }


def _normalize_status(value: object) -> str:
    status = str(value or "played").strip().lower()
    if status in {"dnp", "did_not_play", "did not play", "inactive"}:
        return "dnp"
    if status in {"live", "in_progress", "in-progress", "active"}:
        return "live"
    return "played"


def _best_matching_row(
    rows: list[FinalPlayerStatModel],
    game: object,
    team: object = "",
    target_date: str | None = None,
    placed_date: str | None = None,
    allow_unique_date_fallback: bool = False,
) -> FinalPlayerStatModel | None:
    if not rows:
        return None
    rows = sorted(
        rows,
        key=lambda row: (
            str(row.game_date or ""),
            1 if str(getattr(row, "status", "played") or "played").lower() in {"played", "dnp"} else 0,
            int(getattr(row, "id", 0) or 0),
        ),
        reverse=True,
    )
    requested_game = str(game or "").strip()
    if not requested_game:
        rows = _rows_near_target_date(rows, target_date)
        if not rows:
            return None
        if placed_date:
            dated = [row for row in rows if str(row.game_date or "") >= placed_date]
            if dated:
                return dated[-1] if len(dated) == 1 else dated[0]
        return rows[0] if len(rows) == 1 else None

    requested_key = _game_key(requested_game)
    if not requested_key:
        return rows[0] if len(rows) == 1 else None
    if placed_date and not target_date and not _is_full_matchup(requested_game):
        return None

    matched = [row for row in rows if _game_key(row.game) == requested_key]

    team_key = _game_key(team)
    if not matched and team_key:
        matched = [
            row
            for row in rows
            if requested_key in _game_key(row.game) and team_key in _game_key(row.game)
        ]

    if not matched and len(requested_key) <= 4:
        matched = [row for row in rows if requested_key in _game_key(row.game)]

    if not matched and allow_unique_date_fallback:
        matched = _unique_team_row_on_target_date(rows, team, target_date)
    if not matched:
        return None

    nearby_matched = _rows_near_target_date(matched, target_date)
    if not nearby_matched and _is_full_matchup(requested_game) and _rows_allow_extended_date_recovery(matched):
        nearby_matched = _unique_matchup_row_within_days(matched, target_date, max_days=7)
    matched = nearby_matched
    if not matched and allow_unique_date_fallback:
        matched = _unique_team_row_on_target_date(rows, team, target_date)
    if not matched:
        return None
    if placed_date:
        placed_rows = [row for row in matched if str(row.game_date or "") >= placed_date]
        if placed_rows:
            matched = placed_rows
    return matched[0]


def _unique_team_row_on_target_date(
    rows: list[FinalPlayerStatModel],
    team: object,
    target_date: str | None,
) -> list[FinalPlayerStatModel]:
    """Recover from a bad opponent code only when date and team prove one game."""
    if not target_date:
        return []
    dated = [row for row in rows if str(row.game_date or "") == target_date]
    team_key = _game_key(team)
    if team_key:
        dated = [row for row in dated if team_key in _game_key(row.game)]
    game_keys = {_game_key(row.game) for row in dated if _game_key(row.game)}
    return dated if len(game_keys) == 1 else []


def _rows_near_target_date(
    rows: list[FinalPlayerStatModel],
    target_date: str | None,
) -> list[FinalPlayerStatModel]:
    if not target_date:
        return rows
    exact = [row for row in rows if str(row.game_date or "") == target_date]
    if exact:
        return exact
    if any(str(getattr(row, "sport", "") or "").upper() == "MLB" for row in rows):
        return []
    try:
        requested = date.fromisoformat(target_date)
    except ValueError:
        return []
    return [
        row
        for row in rows
        if _date_distance(row.game_date, requested) <= 1
    ]


def _unique_matchup_row_within_days(
    rows: list[FinalPlayerStatModel],
    target_date: str | None,
    max_days: int,
) -> list[FinalPlayerStatModel]:
    """Recover an incorrect saved date only when one exact matchup is possible."""
    if not target_date:
        return []
    try:
        requested = date.fromisoformat(target_date)
    except ValueError:
        return []
    nearby = [row for row in rows if _date_distance(row.game_date, requested) <= max_days]
    dates = {str(row.game_date or "") for row in nearby}
    return nearby if len(dates) == 1 else []


def _is_full_matchup(value: object) -> bool:
    text = str(value or "").upper()
    return "@" in text or " VS " in text or " VS. " in text or " VERSUS " in text


def _rows_allow_extended_date_recovery(rows: list[FinalPlayerStatModel]) -> bool:
    sports = {
        sport for row in rows
        if (sport := str(getattr(row, "sport", "") or "").upper())
    }
    return not sports or sports.issubset({"NBA", "WNBA", "NFL", "NCAAF"})


def _date_distance(value: object, target: date) -> int:
    try:
        parsed = date.fromisoformat(str(value or ""))
    except ValueError:
        return 9999
    return abs((parsed - target).days)


def _best_fuzzy_player_row(session, prop: dict) -> FinalPlayerStatModel | None:
    player_key = _person_key(prop.get("player", ""))
    if not player_key:
        return None

    query = (
        session.query(FinalPlayerStatModel)
        .filter(FinalPlayerStatModel.sport == prop.get("sport", ""))
        .filter(FinalPlayerStatModel.stat.in_(stat_alias_labels(prop.get("stat", ""))))
    )
    excluded_sources = [
        str(source).strip().lower()
        for source in prop.get("_excluded_sources", [])
        if str(source).strip()
    ]
    if excluded_sources:
        query = query.filter(~FinalPlayerStatModel.source.in_(excluded_sources))
    rows = query.order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc()).limit(250).all()
    if not rows:
        return None

    game = prop.get("game", "")
    team = prop.get("team", "")
    candidates = [row for row in rows if _player_name_matches(player_key, row.player)]
    if not candidates:
        return None

    return _best_matching_row(
        candidates,
        game,
        team,
        target_date=_prop_game_date(prop),
        placed_date=_prop_placed_date(prop),
    )


def _prop_game_date(prop: dict) -> str | None:
    game_time = str(prop.get("game_time") or "").strip()
    if not game_time:
        return None
    try:
        parsed = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo("America/New_York"))
    return parsed.date().isoformat()


def _prop_placed_date(prop: dict) -> str | None:
    placed = prop.get("_placed_date")
    if placed is None:
        return None
    if hasattr(placed, "isoformat"):
        return placed.isoformat()
    text = str(placed or "").strip()
    return text[:10] if text else None


def _player_name_matches(requested_key: str, provider_name: object) -> bool:
    provider_key = _person_key(provider_name)
    if not provider_key:
        return False
    if requested_key == provider_key:
        return True
    if _last_name(requested_key) != _last_name(provider_key):
        return False
    return SequenceMatcher(None, requested_key, provider_key).ratio() >= 0.9


def _person_key(value: object) -> str:
    return canonical_person_key(value)


def _last_name(person_key: str) -> str:
    return person_key[-8:]


def _game_key(value: object) -> str:
    return canonical_matchup_key(value, _TEAM_ALIASES)


_TEAM_ALIASES = {
    "NYL": "NY",
    "LVA": "LV",
    "LAS": "LA",
    "WAS": "WSH",
    "GSV": "GS",
    "PDX": "POR",
    "AZ": "ARI",
    "CWS": "CHW",
}


def _entry_prop_history(session, player: str, stat: str, sport: str | None, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    query = (
        session.query(EntryPropModel, EntryModel)
        .join(EntryModel, EntryModel.id == EntryPropModel.entry_id)
        .filter(EntryModel.status == "Settled")
        .filter(EntryPropModel.stat.in_(stat_alias_labels(stat)))
        .filter(EntryPropModel.actual.isnot(None))
        .filter(EntryPropModel.final_source != "")
        .filter(EntryPropModel.final_source != "projection_estimate")
    )
    if sport:
        query = query.filter(EntryPropModel.sport == sport)
    player_key = canonical_person_key(player)
    ordered = query.order_by(EntryModel.settled_at.desc(), EntryPropModel.id.desc())
    # Most lookups have an exact provider spelling. Filter those in SQL so a
    # projection does not materialize the entire settled ledger for every
    # candidate prop. Keep the canonical fallback for accents and aliases.
    rows = (
        ordered.filter(func.lower(EntryPropModel.player_name) == str(player).strip().lower())
        .limit(limit)
        .all()
    )
    if not rows:
        candidates = ordered.limit(max(limit * 8, limit)).all()
        rows = [
            (prop, entry)
            for prop, entry in candidates
            if canonical_person_key(prop.player_name) == player_key
        ][:limit]
    return [
        {
            "player": prop.player_name,
            "team": prop.team,
            "sport": prop.sport,
            "stat": prop.stat,
            "game": prop.game,
            "game_date": entry.settled_at.date().isoformat() if entry.settled_at else "",
            "actual": prop.actual,
            "status": prop.final_status or "played",
            "source": prop.final_source or "edgeiq_entry",
            "entry_id": entry.id,
            "result": prop.final_result,
        }
        for prop, entry in rows
    ]

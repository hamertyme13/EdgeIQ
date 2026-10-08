"""Bounded fallback matching when a provider player has no identity record."""

from __future__ import annotations

from collections.abc import Collection

from repository.models.final_player_stat_model import FinalPlayerStatModel
from utils.entity_normalization import canonical_person_key

MAX_NAME_CANDIDATES = 5000


def recent_canonical_player_ids(
    session,
    player: str,
    *,
    sport: str | None = None,
    stats: Collection[str] | None = None,
) -> list[int]:
    key = canonical_person_key(player)
    if not key:
        return []
    query = session.query(FinalPlayerStatModel.id, FinalPlayerStatModel.player)
    if sport:
        query = query.filter(FinalPlayerStatModel.sport == sport.upper())
    if stats:
        query = query.filter(FinalPlayerStatModel.stat.in_(stats))
    rows = query.order_by(
        FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc(),
    ).limit(MAX_NAME_CANDIDATES).all()
    return [row.id for row in rows if canonical_person_key(row.player) == key]

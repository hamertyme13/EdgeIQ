"""Exact-offer linking for generated cards before their final entry review."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from services.offer_snapshot import offer_fingerprint, parsed_utc


def link_current_offer_snapshots(
    props: list[dict], lookup: Callable[[str], dict | None], *, now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC)
    linked = 0
    for prop in props:
        prop["offer_snapshot_id"] = ""
        fingerprint = offer_fingerprint(prop)
        if not fingerprint:
            continue
        snapshot = lookup(fingerprint)
        if not snapshot:
            continue
        observed = parsed_utc(snapshot.get("last_observed_at"))
        expires = parsed_utc(snapshot.get("expires_at"))
        game_start = parsed_utc(snapshot.get("game_start"))
        if not observed or not expires or observed > current or expires <= current:
            continue
        if game_start and game_start <= current:
            continue
        prop["offer_snapshot_id"] = fingerprint
        linked += 1
    return linked

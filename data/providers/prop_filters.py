"""Shared filters for provider prop feeds."""

from __future__ import annotations

import re


_COMBO_MARKERS = (
    "combo",
    "combined",
    "2 players",
    "two players",
    "teammates",
    "duo",
)


def is_combined_player_prop(prop: dict) -> bool:
    """Return True for props where one line depends on multiple players.

    Same-player stat combinations such as PRA or Points + Rebounds remain
    allowed. This only catches labels that identify multiple player names or a
    provider-combo market.
    """
    player = str(prop.get("player") or prop.get("player_name") or "").strip()
    stat = str(prop.get("stat") or prop.get("market") or "").strip()
    description = str(prop.get("description") or prop.get("game") or "").strip()
    haystack = f"{player} {stat} {description}".lower()
    if any(marker in haystack for marker in _COMBO_MARKERS):
        return True
    return _looks_like_multiple_player_names(player)


def _looks_like_multiple_player_names(player: str) -> bool:
    if not player:
        return False
    normalized = player.replace("／", "/").replace("＆", "&")
    separators = (r"\s+\+\s+", r"\s+&\s+", r"\s+and\s+", r"\s*/\s*", r"\s*,\s*")
    for pattern in separators:
        parts = [part.strip() for part in re.split(pattern, normalized, maxsplit=1) if part.strip()]
        if len(parts) >= 2 and all(_looks_like_person_name(part) for part in parts[:2]):
            return True
    return False


def _looks_like_person_name(value: str) -> bool:
    words = [word for word in re.split(r"\s+", value.strip()) if word]
    alpha_words = [word for word in words if any(character.isalpha() for character in word)]
    return len(alpha_words) >= 2

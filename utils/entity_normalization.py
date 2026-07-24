from __future__ import annotations

import re
import unicodedata


def canonical_person_key(value: object) -> str:
    """Return an accent-insensitive key for matching the same person across providers."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(character for character in text if not unicodedata.combining(character))
    return "".join(character for character in ascii_text.casefold() if character.isalnum())


def same_person(left: object, right: object) -> bool:
    left_key = canonical_person_key(left)
    return bool(left_key) and left_key == canonical_person_key(right)


def canonical_matchup_key(value: object, aliases: dict[str, str] | None = None) -> str:
    """Normalize a two-team matchup without treating home/away order as identity."""
    text = unicodedata.normalize("NFKD", str(value or "")).upper().strip()
    if not text:
        return ""
    normalized = re.sub(r"\s+(?:VS\.?|V\.?|AT)\s+", "@", text)
    parts = [part.strip() for part in re.split(r"[@/]", normalized) if part.strip()]
    keys = [_team_key(part, aliases or {}) for part in parts]
    keys = [key for key in keys if key]
    if len(keys) == 2:
        return "@".join(sorted(keys))
    return _team_key(normalized, aliases or {})


def _team_key(value: object, aliases: dict[str, str]) -> str:
    key = "".join(character for character in str(value or "").upper() if character.isalnum())
    return aliases.get(key, key)

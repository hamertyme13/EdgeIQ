from __future__ import annotations

import re

from models.stat_type import StatType
from utils.stat_normalization import canonical_stat_label

_PARTIAL_GAME_PATTERN = re.compile(
    r"(?:^|\s)(?:"
    r"[1-4](?:q|st quarter|nd quarter|rd quarter|th quarter)|"
    r"[1-9](?:st|nd|rd|th)? inning|"
    r"1h|2h|first half|second half|first period|second period|third period|"
    r"first quarter|second quarter|third quarter|fourth quarter"
    r")(?:\s|$)",
    flags=re.IGNORECASE,
)


def is_partial_game_market(stat: object) -> bool:
    return bool(_PARTIAL_GAME_PATTERN.search(str(stat or "").replace("-", " ").strip()))


def is_supported_full_game_stat(stat: object) -> bool:
    if is_partial_game_market(stat):
        return False
    canonical = canonical_stat_label(stat)
    return canonical in {candidate.value for candidate in StatType}

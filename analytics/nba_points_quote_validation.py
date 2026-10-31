"""Read-only evaluation of selected, pregame NBA Points market quotes."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from math import isfinite
from zoneinfo import ZoneInfo

from utils.entity_normalization import canonical_matchup_key, canonical_person_key

VERIFIED_SOURCES = ("espn", "nba_api", "statshawk", "balldontlie")
TEAM_ALIASES = {"SAS": "SA", "GSW": "GS", "NYK": "NY"}
MAX_PAIRED_QUOTE_GAP = timedelta(minutes=30)


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _game_key(game: object) -> str:
    return canonical_matchup_key(game, TEAM_ALIASES)


def _brier(rows: list[dict], probability: str) -> float | None:
    if not rows:
        return None
    return round(sum((row[probability] - row["outcome"]) ** 2 for row in rows) / len(rows), 4)


def _version_checks(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["model_probability"] is not None and row["model_version"]:
            grouped[row["model_version"]].append(row)
    results = []
    for version, cohort in sorted(grouped.items()):
        dates = sorted({row["game_date"] for row in cohort})
        result = {
            "model_version": version,
            "samples": len(cohort),
            "game_dates": len(dates),
            "model_brier": _brier(cohort, "model_probability"),
            "market_brier": _brier(cohort, "market_probability"),
            "later_games": None,
        }
        if len(cohort) >= 30 and len(dates) >= 5:
            cutoff = dates[max(1, int(len(dates) * 0.7))]
            later = [row for row in cohort if row["game_date"] >= cutoff]
            if len(later) >= 10:
                result["later_games"] = {
                    "from_game_date": cutoff,
                    "samples": len(later),
                    "model_brier": _brier(later, "model_probability"),
                    "market_brier": _brier(later, "market_probability"),
                }
        results.append(result)
    return results


def _paired_version_checks(rows: dict[tuple, dict]) -> list[dict]:
    by_version: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for key, row in rows.items():
        by_version[key[-1]][key[:-1]] = row
    results = []
    for first, second in combinations(sorted(by_version), 2):
        overlap = sorted(
            set(by_version[first]) & set(by_version[second]),
            key=lambda key: (min(by_version[first][key]["captured_at"], by_version[second][key]["captured_at"]), key),
        )
        if not overlap:
            continue
        matched = []
        seen_player_games = set()
        time_mismatches = 0
        for key in overlap:
            if key[:3] in seen_player_games:
                continue
            left, right = by_version[first][key], by_version[second][key]
            if abs(left["captured_at"] - right["captured_at"]) > MAX_PAIRED_QUOTE_GAP:
                time_mismatches += 1
                continue
            seen_player_games.add(key[:3])
            matched.append((left, right))
        dates = sorted({left["game_date"] for left, _ in matched})
        result = {
            "first_version": first, "second_version": second,
            "samples": len(matched), "game_dates": len(dates),
            "quote_time_mismatches": time_mismatches,
            "first_brier": _brier([left for left, _ in matched], "model_probability"),
            "second_brier": _brier([right for _, right in matched], "model_probability"),
            "later_games": None,
        }
        if len(matched) >= 30 and len(dates) >= 5:
            cutoff = dates[max(1, int(len(dates) * 0.7))]
            later = [(left, right) for left, right in matched if left["game_date"] >= cutoff]
            if len(later) >= 10:
                result["later_games"] = {
                    "from_game_date": cutoff, "samples": len(later),
                    "first_brier": _brier([left for left, _ in later], "model_probability"),
                    "second_brier": _brier([right for _, right in later], "model_probability"),
                }
        results.append(result)
    return results


def evaluate_nba_points_quotes(inputs: dict, *, now: datetime | None = None) -> dict:
    """One earliest quote per player-game; no entries or model releases are changed."""
    quotes = inputs.get("quotes") or []
    if inputs.get("finals_truncated"):
        return {"status": "unavailable", "reason": "The verified-final scan hit its safety limit; no quote scores were calculated.",
                "examined": len(quotes), "eligible_independent": 0}
    current = now or datetime.now(UTC)
    finals: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in inputs.get("finals") or []:
        if str(row.get("source") or "").lower() in VERIFIED_SOURCES and str(row.get("status") or "").lower() == "played":
            key = (canonical_person_key(row.get("player")), _game_key(row.get("game")), str(row.get("game_date") or "")[:10])
            finals[key].append(row)
    excluded: Counter[str] = Counter()
    selected: dict[tuple[str, str, str], dict] = {}
    version_selected: dict[tuple[str, str, str, str], dict] = {}
    exact_line_selected: dict[tuple[str, str, str, float, str], dict] = {}
    for quote in sorted(quotes, key=lambda row: _time(row.get("captured_at")) or datetime.max.replace(tzinfo=UTC)):
        captured = _time(quote.get("captured_at"))
        oldest = _time(quote.get("oldest_quote_at"))
        game_time = _time(quote.get("game_time"))
        if not captured or not oldest or not game_time or not oldest <= captured < game_time:
            excluded["not_locked_pregame"] += 1
            continue
        if captured - oldest > timedelta(minutes=30) or oldest - captured > timedelta(minutes=2):
            excluded["stale_or_future_quote"] += 1
            continue
        if game_time >= current:
            excluded["game_not_started"] += 1
            continue
        line = _number(quote.get("line"))
        market = _number(quote.get("market_over_probability"))
        under = _number(quote.get("market_under_probability"))
        try:
            book_count = int(quote.get("book_count"))
        except (TypeError, ValueError):
            book_count = 0
        if (line is None or line <= 0 or market is None or under is None
                or not 0 <= market <= 100 or not 0 <= under <= 100 or abs(market + under - 100) > 1
                or book_count < 1 or not quote.get("market_event_id")):
            excluded["invalid_quote"] += 1
            continue
        player_key = canonical_person_key(quote.get("player"))
        matchup = _game_key(quote.get("game"))
        day = game_time.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if not player_key or "@" not in matchup:
            excluded["missing_identity"] += 1
            continue
        identity = (player_key, matchup, day)
        matches = finals.get(identity) or []
        if not matches:
            excluded["no_verified_final"] += 1
            continue
        if {str(row.get("season_type") or "").lower() for row in matches} != {"regular"}:
            excluded["season_unverified"] += 1
            continue
        actuals = {_number(row.get("actual")) for row in matches}
        if None in actuals or len(actuals) != 1:
            excluded["conflicting_final"] += 1
            continue
        actual = next(iter(actuals))
        if actual == line:
            excluded["push"] += 1
            continue
        model = _number(quote.get("model_over_probability"))
        outcome = {
            "outcome": int(actual > line), "market_probability": market / 100,
            "model_probability": model / 100 if model is not None and 0 <= model <= 100 else None,
            "game_date": day,
            "captured_at": captured,
            "model_version": str(quote.get("model_version") or "").strip(),
        }
        if outcome["model_probability"] is not None and outcome["model_version"]:
            version_selected.setdefault((*identity, outcome["model_version"]), outcome)
            exact_line_selected.setdefault((*identity, line, outcome["model_version"]), outcome)
        if identity in selected:
            excluded["duplicate_player_game"] += 1
            continue
        selected[identity] = outcome
    rows = list(selected.values())
    market_brier = sum((row["market_probability"] - row["outcome"]) ** 2 for row in rows) / len(rows) if rows else None
    paired = [row for row in rows if row["model_probability"] is not None]
    return {
        "status": "exploratory" if rows else "insufficient_evidence",
        "examined": len(quotes), "eligible_independent": len(rows),
        "quote_limit_reached": bool(inputs.get("quote_limit_reached")),
        "excluded": dict(sorted(excluded.items())),
        "market": {
            "samples": len(rows),
            "brier": round(market_brier, 4) if market_brier is not None else None,
            "predicted_over_rate": round(100 * sum(row["market_probability"] for row in rows) / len(rows), 1) if rows else None,
            "actual_over_rate": round(100 * sum(row["outcome"] for row in rows) / len(rows), 1) if rows else None,
        },
        "paired": {
            "samples": len(paired),
            "market_brier": round(sum((row["market_probability"] - row["outcome"]) ** 2 for row in paired) / len(paired), 4) if paired else None,
            "model_brier": round(sum((row["model_probability"] - row["outcome"]) ** 2 for row in paired) / len(paired), 4) if paired else None,
        },
        "versions": _version_checks(list(version_selected.values())),
        "paired_versions": _paired_version_checks(exact_line_selected),
        "promotion_ready": False,
        "note": "Selected on-demand quotes only. A sportsbook no-vig probability is not a DFS payout, CLV, or validated betting edge.",
    }

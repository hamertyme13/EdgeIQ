"""Check quantitative answer claims against typed facts in cited evidence."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from utils.entity_normalization import canonical_person_key

NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?!\w)")
MAX_FACTS = 300
FIELD_TYPES = {
    "line": "line", "requested_line": "line", "original_line": "line", "current_line": "line",
    "projection": "projection", "projected": "projection", "expected_result": "projection",
    "median": "projection", "forecast": "projection",
    "confidence": "probability", "probability": "probability", "model_probability": "probability",
    "calibrated_probability": "probability", "hit_rate": "probability", "win_probability": "probability",
    "sample_size": "sample", "segment_sample_size": "sample", "history_count": "sample",
    "actual": "result", "result": "result", "final_result": "result",
    "expected_value": "value", "ev": "value", "edge": "value",
    "score": "score", "edgeiq_score": "score", "model_trust": "score",
    "wager": "stake", "stake": "stake",
}
CLAIM_TERMS = {
    "line": re.compile(r"\b(line|over|under)\b", re.I),
    "projection": re.compile(r"\b(projection|projected|projects|forecast|expected result|median)\b", re.I),
    "probability": re.compile(r"\b(confidence|probability|chance|hit rate|win rate)\b", re.I),
    "sample": re.compile(r"\b(samples?|tracked games|history count)\b", re.I),
    "result": re.compile(r"\b(actual|final result|scored|finished with)\b", re.I),
    "value": re.compile(r"\b(expected value|\bEV\b|edge)\b", re.I),
    "score": re.compile(r"\b(score|model trust)\b", re.I),
    "stake": re.compile(r"\b(wager|stake)\b", re.I),
}
STATUS_ASSERTION_RE = re.compile(
    r"\b(?:is|was|has been|listed as|ruled)\s+(?:officially\s+|confirmed\s+|currently\s+)?"
    r"(?P<status>out|inactive|questionable|doubtful|probable|starting|a starter|active|available)\b(?!\s+of\b)",
    re.I,
)
STATUS_CONTEXT_RE = re.compile(r"\b(?:if|whether|no evidence|not confirmed|unknown if)\b", re.I)
NONPLAYER_SUBJECT_RE = re.compile(r"\b(?:model|game|market|entry|analysis|sample|line|offer|season)\s+$", re.I)


@dataclass(frozen=True)
class Fact:
    id: str
    citation_id: str
    kind: str
    value: float
    player_key: str
    player_name: str


def cited_facts(bundle: dict, cited_ids: set[str]) -> list[Fact]:
    facts: list[Fact] = []

    def visit(value: object, citation_id: str, path: str, player_key: str, player_name: str) -> None:
        if len(facts) >= MAX_FACTS:
            return
        if isinstance(value, dict):
            player_name = str(value.get("player") or player_name)
            player_key = canonical_person_key(player_name)
            for key, child in value.items():
                visit(child, citation_id, f"{path}.{key}" if path else str(key), player_key, player_name)
        elif isinstance(value, list):
            for index, child in enumerate(value[:20]):
                visit(child, citation_id, f"{path}[{index}]", player_key, player_name)
        elif (isinstance(value, (int, float)) and not isinstance(value, bool)) or (
            isinstance(value, str) and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value.strip())
        ):
            number = float(value)
            if math.isfinite(number):
                kind = FIELD_TYPES.get(path.rsplit(".", 1)[-1])
                if kind:
                    facts.append(Fact(f"fact:{citation_id}:{path}", citation_id, kind, number, player_key, player_name))

    for citation in bundle.get("citations") or []:
        citation_id = str(citation.get("id") or "")
        if citation_id in cited_ids:
            visit(citation.get("data"), citation_id, "", "", "")
    return facts


def unsupported_fact_claim(answer: dict, bundle: dict) -> bool:
    """Fail closed when a quantitative claim lacks a matching cited field."""
    _, unsupported = claim_fact_references(answer, bundle)
    return unsupported


def claim_fact_references(answer: dict, bundle: dict) -> tuple[list[dict], bool]:
    """Link numeric claims to exact cited fields after applying the grounding rules."""
    cited_ids = set(answer.get("citations") or [])
    facts = cited_facts(bundle, cited_ids)
    summary = bundle.get("summary") or {}
    requested_line = (summary.get("query_context") or {}).get("requested_line")
    fields = [(key, str(answer.get(key) or "")) for key in (
        "answer", "recommendation", "counterargument", "suggested_correction",
    )]
    fields.extend((f"supporting_evidence[{index}]", str(value)) for index, value in enumerate(
        answer.get("supporting_evidence") or [],
    ))
    fields.extend((f"missing_information[{index}]", str(value)) for index, value in enumerate(
        answer.get("missing_information") or [],
    ))
    references: list[dict] = []
    for field_name, text in fields:
        for match in NUMBER_RE.finditer(text):
            number = float(match.group())
            kind = _nearest_kind(text, match.start(), match.end())
            if number <= 10 and kind is None:
                continue  # Card leg counts and ordinal labels are not market measurements.
            if (kind == "line"
                    and re.search(r"\brequested line\b", text[max(0, match.start() - 30):match.end()], re.I)
                    and _same(number, requested_line)):
                continue  # A user-entered line is context, not a current provider quote.
            named_players = _nearest_players(text, match.start(), facts)
            matching = [fact for fact in facts if
                (_same(number, fact.value) or (fact.kind == "probability" and 0 <= fact.value <= 1 and _same(number, fact.value * 100)))
                and (kind is None or fact.kind == kind)
                and (not named_players or fact.player_key in named_players)
            ]
            if not matching:
                return references, True
            if len(matching) == 1:
                references.append({
                    "field": field_name, "number": match.group(),
                    "fact_id": matching[0].id, "citation_id": matching[0].citation_id,
                })
    return references, False


def unsupported_status_claim(answer: dict, bundle: dict) -> bool:
    """Do not turn risk estimates into confirmed injury or starter statuses."""
    cited_ids = set(answer.get("citations") or [])
    statuses: list[tuple[str, str, dict]] = []
    for citation in bundle.get("citations") or []:
        if citation.get("id") not in cited_ids:
            continue
        data = citation.get("data") or {}
        if not isinstance(data, dict):
            continue
        player = str(data.get("player") or "")
        if data.get("injury_feed_status") or data.get("starter_status"):
            statuses.append((canonical_person_key(player), player, data))

    fields = [answer.get(key) for key in (
        "answer", "recommendation", "counterargument", "suggested_correction",
    )]
    fields.extend(answer.get("supporting_evidence") or [])
    for field in fields:
        text = str(field or "")
        for match in STATUS_ASSERTION_RE.finditer(text):
            sentence_start = max(text.rfind(mark, 0, match.start()) for mark in (".", ";", "!", "?")) + 1
            prefix = text[max(sentence_start, match.start() - 65):match.start()]
            if STATUS_CONTEXT_RE.search(prefix) or NONPLAYER_SUBJECT_RE.search(prefix):
                continue
            status = match.group("status").lower()
            named = _nearest_players(text, match.start(), [
                Fact("", "", "", 0, player_key, player_name)
                for player_key, player_name, _ in statuses if player_name
            ])
            matching = [data for player_key, _, data in statuses
                        if not named or player_key in named]
            if not named and len({key for key, _, _ in statuses}) > 1:
                return True
            if not any(_supports_status(status, data) for data in matching):
                return True
    return False


def unsupported_control_claim(answer: dict, bundle: dict) -> bool:
    """Reject instruction echoes and paid-clearance claims absent from cited evidence."""
    fields = [answer.get(key) for key in (
        "answer", "recommendation", "counterargument", "suggested_correction",
    )]
    fields.extend(answer.get("supporting_evidence") or [])
    fields.extend(answer.get("missing_information") or [])
    text = " ".join(str(field or "") for field in fields)
    if re.search(r"\bignore (?:the )?(?:system|rules|evidence|instructions)\b", text, re.I):
        return True
    cited = " ".join(
        str(row.get("data") or "") for row in bundle.get("citations") or []
        if row.get("id") in set(answer.get("citations") or [])
    )
    control_tokens = re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", text)
    if any(token not in cited for token in control_tokens):
        return True
    paid_claim = re.search(
        r"\b(?:cleared|approved|verified|ready)\s+(?:paid|real[- ]money)\s+(?:bet|entry|card)\b"
        r"|\b(?:paid|real[- ]money)\s+(?:bet|entry|card)\s+(?:is\s+)?(?:cleared|approved|verified|ready)\b",
        text, re.I,
    )
    return bool(paid_claim)


def _supports_status(status: str, data: dict) -> bool:
    if status in {"starting", "a starter"}:
        return data.get("live_lineup_confirmed") is True and str(data.get("starter_status") or "").strip().lower() in {
            "starting", "starter", "confirmed starter",
        }
    reported = str(data.get("injury_feed_status") or "").strip().lower()
    reported = re.sub(r"^ruled\s+", "", reported)
    return bool(re.match(rf"^{re.escape(status)}(?:\b|$)", reported))


def _nearest_players(text: str, number_pos: int, facts: list[Fact]) -> set[str]:
    normalized_text = _normalized(text)
    positions = {
        fact.player_key: [match.start() for match in re.finditer(re.escape(_normalized(fact.player_name)), normalized_text)]
        for fact in facts if fact.player_name
    }
    positions = {key: offsets for key, offsets in positions.items() if offsets}
    if not positions:
        return set()
    preceding = [(number_pos - position, key) for key, offsets in positions.items()
                 for position in offsets if position < number_pos]
    following = [(position - number_pos, key) for key, offsets in positions.items()
                 for position in offsets if position >= number_pos]
    closest = min(preceding or following)
    return {closest[1]}


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in text if not unicodedata.combining(character))


def _nearest_kind(text: str, start: int, end: int) -> str | None:
    nearest: tuple[int, str] | None = None
    for kind, pattern in CLAIM_TERMS.items():
        for match in pattern.finditer(text):
            distance = max(match.start() - end, start - match.end(), 0)
            if distance <= 24 and (nearest is None or distance < nearest[0]):
                nearest = (distance, kind)
    return nearest[1] if nearest else None


def _same(left: float, right: object) -> bool:
    try:
        return abs(left - float(str(right))) < 0.011
    except (TypeError, ValueError):
        return False

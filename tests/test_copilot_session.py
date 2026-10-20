from datetime import UTC, datetime, timedelta, timezone

from web.application.copilot_service import copilot_query_payload
from web.application.copilot_session import resolve_followup
from web.schemas.predictions import CopilotFocus, CopilotQueryPayload

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _payload(question="What about her rebounds?", **changes):
    data = {
        "question": question, "sport": "WNBA", "platform": "PrizePicks",
        "focus": CopilotFocus(player="A'ja Wilson", sport="WNBA", platform="PrizePicks",
                              stat="Points", updated_at=NOW),
        "line": 25.5,
    }
    data.update(changes)
    return CopilotQueryPayload(**data)


def test_followup_resolves_player_and_new_stat_without_old_line():
    resolved, missing = resolve_followup(_payload(), now=NOW + timedelta(minutes=5))
    assert not missing
    assert (resolved.player, resolved.stat, resolved.line) == ("A'ja Wilson", "Rebounds", None)


def test_expired_or_switched_focus_requires_explicit_player():
    assert resolve_followup(_payload(), now=NOW + timedelta(minutes=46))[1]
    assert resolve_followup(_payload(sport="NBA"), now=NOW)[1]
    assert resolve_followup(_payload(platform="Underdog"), now=NOW)[1]
    assert resolve_followup(_payload(question="What about her points and rebounds?"), now=NOW)[1]
    assert resolve_followup(_payload(focus=None), now=NOW)[1]


def test_explicit_player_overrides_old_focus():
    resolved, missing = resolve_followup(_payload(player="Breanna Stewart", stat="Rebounds"), now=NOW)
    assert not missing
    assert resolved.player == "Breanna Stewart"
    assert not resolve_followup(_payload(question="What about tonight's games?", focus=None), now=NOW)[1]


def test_research_returns_focus_only_when_evidence_exists(monkeypatch):
    monkeypatch.setattr("web.application.copilot_service.ollama_structured", lambda *_args, **_kwargs: (None, "offline"))
    calls = []
    result = copilot_query_payload(
        CopilotQueryPayload(question="Research this player", player="A'ja Wilson", stat="Points",
                            sport="WNBA", platform="PrizePicks"),
        player_research=lambda *args: (calls.append(args) or {
            "player": "A'ja Wilson", "history_count": 4, "chart": [],
        }),
        loss_review=lambda: {}, briefing=lambda *_args: {}, portfolio=lambda: {},
    )
    assert calls and result["focus"]["player"] == "A'ja Wilson"
    assert result["focus"]["sport"] == "WNBA"


def test_followup_fetches_new_stat_instead_of_reusing_old_offer(monkeypatch):
    monkeypatch.setattr("web.application.copilot_service.ollama_structured", lambda *_args, **_kwargs: (None, "offline"))
    calls = []
    payload = _payload(focus=CopilotFocus(
        player="A'ja Wilson", sport="WNBA", platform="PrizePicks", stat="Points",
        updated_at=datetime.now(UTC),
    ))
    result = copilot_query_payload(
        payload,
        player_research=lambda *args: (calls.append(args) or {"history_count": 1, "player": "A'ja Wilson"}),
        loss_review=lambda: {}, briefing=lambda *_args: {}, portfolio=lambda: {},
    )
    assert calls == [("A'ja Wilson", "Rebounds", "WNBA", "PrizePicks", None)]
    assert result["focus"]["stat"] == "Rebounds"

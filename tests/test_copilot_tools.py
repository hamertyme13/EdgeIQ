import pytest
from pydantic import ValidationError

from web.application.copilot_tools import ToolContext, invoke_tool


def _context():
    return ToolContext(
        cached_briefing=lambda platform, sport: {
            "top_opportunities": [{"player": str(index)} for index in range(20)],
            "slate_changes": {"available": False},
            "as_of": "snapshot",
        },
        portfolio=lambda: {"pending_real_entries": 1},
        personal_edge=lambda mode: {"mode": mode},
        timeline=lambda **kwargs: kwargs,
        track_record=lambda **kwargs: kwargs,
    )


def test_only_named_read_only_tools_are_available():
    context = _context()
    for name in ("refresh_provider", "write_entry", "execute_sql", "fetch_url"):
        with pytest.raises(ValueError, match="not available"):
            invoke_tool(name, {}, context)
    with pytest.raises(ValidationError):
        invoke_tool("portfolio_risk", {"user_id": "someone_else"}, context)
    with pytest.raises(ValidationError):
        invoke_tool("cached_briefing", {"platform": "PrizePicks", "sport": "WNBA", "refresh": True}, context)


def test_tool_queries_are_bounded_and_use_cached_callbacks():
    context = _context()
    assert len(invoke_tool("cached_briefing", {"platform": "PrizePicks", "sport": "WNBA"}, context)["top_opportunities"]) == 9
    assert invoke_tool("recommendation_timeline", {"player": "Player", "sport": "WNBA", "limit": 30}, context)["limit"] == 30
    with pytest.raises(ValidationError):
        invoke_tool("recommendation_timeline", {"player": "Player", "limit": 31}, context)
    with pytest.raises(ValidationError):
        invoke_tool("model_track_record", {"sport": "Unknown"}, context)
    with pytest.raises(ValidationError):
        invoke_tool("personal_edge", {"mode": "all_users"}, context)

import asyncio
import json

from web.routers.intelligence import IntelligenceDependencies, ai_copilot_stream
from web.schemas import CopilotQueryPayload


def _deps(query):
    empty = lambda *_args: {}
    return IntelligenceDependencies(
        parlay_chat=empty, ai_status=empty, entry_review=empty, trending_games=empty,
        game_context=empty, ev_analysis=empty, projection_assist=empty,
        copilot_query=query, explain_recommendation=empty, evaluate_model=empty,
    )


def _events(query):
    async def read():
        response = await ai_copilot_stream(CopilotQueryPayload(question="Research player"), _deps(query))
        return [chunk async for chunk in response.body_iterator]

    return asyncio.run(read())


def test_stream_reports_real_stages_before_validated_answer():
    def query(_payload, progress):
        progress("planning", "Interpreting your question")
        progress("retrieval", "Checking saved EdgeIQ evidence")
        return {"grounded": True, "response": {"answer": "Checked result"}}

    chunks = _events(query)
    assert [chunk.split("\n", 1)[0] for chunk in chunks] == [
        "event: status", "event: status", "event: answer", "event: done",
    ]
    assert json.loads(chunks[2].split("data: ", 1)[1])["response"]["answer"] == "Checked result"
    assert all("Checked result" not in chunk for chunk in chunks[:2])


def test_stream_fails_closed_without_partial_answer():
    def query(_payload, progress):
        progress("planning", "Interpreting your question")
        raise RuntimeError("private provider detail")

    chunks = _events(query)
    assert [chunk.split("\n", 1)[0] for chunk in chunks] == ["event: status", "event: error", "event: done"]
    assert "private provider detail" not in "".join(chunks)

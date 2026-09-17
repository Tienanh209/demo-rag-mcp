"""The citation list returned to every client (web, CLI, demo script) must be
exactly what the answer cites — not everything retrieval happened to fetch.

Three states used to exist here: "all retrieved passages" (the original bug —
a model that forgot its [n] markers turned every passage into a claimed
source), then "all passages, flagged cited:true/false" (better, but a reader
still had to look past irrelevant chips to find the ones actually used). This
pins the current, filtered behaviour.
"""

import pytest

from src.client.agents.answer_agent import AnswerAgent
from src.client.agents.base import AgentContext
from src.client.memory import ConversationMemory
from src.common.trace import Trace


class _Mem(ConversationMemory):
    def __init__(self):
        self.turns = []
        self.working = type("W", (), {"entities": [], "last_topic": ""})()
        self.summary = ""

    def context_block(self):
        return ""


def _ctx(passages, grounded=True):
    ctx = AgentContext(message="q", memory=_Mem(), mcp=None, trace=Trace())
    ctx.scratch["passages"] = passages
    ctx.scratch["grounded"] = grounded
    ctx.scratch["lang"] = "en"
    ctx.scratch["min_score"] = 0.85
    return ctx


_PASSAGES = [
    {"title": "A", "url": "https://ai.yzu.edu.tw/a", "cite_url": "https://ai.yzu.edu.tw/a",
     "status": "live", "text": "a", "score": 0.95},
    {"title": "B", "url": "https://ai.yzu.edu.tw/b", "cite_url": "https://ai.yzu.edu.tw/b",
     "status": "live", "text": "b", "score": 0.90},
    {"title": "C", "url": "https://ai.yzu.edu.tw/c", "cite_url": "https://ai.yzu.edu.tw/c",
     "status": "archived", "text": "c", "score": 0.88},
]


def _reply(monkeypatch, answer):
    async def fake(system, user, **kw):
        return answer
    monkeypatch.setattr("src.client.agents.answer_agent.llm.complete", fake)


@pytest.mark.asyncio
async def test_only_cited_passages_are_returned(monkeypatch):
    """Retrieval found 3 passages; the answer only used [1]. The other two
    must not appear at all — not dimmed, not flagged, simply absent."""
    _reply(monkeypatch, "The centre offers compute time[1].")
    result = await AnswerAgent().run(_ctx(_PASSAGES))
    assert [c["n"] for c in result.citations] == [1]
    assert result.citations[0]["title"] == "A"


@pytest.mark.asyncio
async def test_every_cited_marker_is_kept_in_order(monkeypatch):
    _reply(monkeypatch, "Facts from [1] and [3], also [1] again.")
    result = await AnswerAgent().run(_ctx(_PASSAGES))
    assert [c["n"] for c in result.citations] == [1, 3]


@pytest.mark.asyncio
async def test_no_markers_falls_back_to_one_passage_not_zero(monkeypatch):
    """An answer with zero visible sources reads as unfounded. When the model
    emits no [n] marker at all, the passage that passed the grounding gate is
    still shown — marked cited:false, since the model never referenced it."""
    _reply(monkeypatch, "The centre offers compute time to students.")
    result = await AnswerAgent().run(_ctx(_PASSAGES))
    assert len(result.citations) == 1
    assert result.citations[0]["n"] == 1
    assert result.citations[0]["cited"] is False


@pytest.mark.asyncio
async def test_refusal_below_grounding_threshold_has_no_citations(monkeypatch):
    async def explode(*a, **kw):
        raise AssertionError("must not generate when ungrounded")
    monkeypatch.setattr("src.client.agents.answer_agent.llm.complete", explode)
    result = await AnswerAgent().run(_ctx(_PASSAGES, grounded=False))
    assert result.citations == []
    assert result.grounded is False

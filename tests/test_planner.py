"""The planner replaced three LLM calls with one, and the fast path with none.

Both properties are easy to lose silently — a refactor that always calls the
model still works, it just costs a request per greeting — so they are pinned
here rather than left to inspection.
"""

from typing import ClassVar

import pytest

from src.client import planner
from src.client.intent import Intent
from src.client.memory import ConversationMemory
from src.client.planner import DEFAULT_TOOL, TurnPlan, normalise_args, plan


class _Mem(ConversationMemory):
    def __init__(self, turns=0):
        self.turns = ["x"] * turns
        self.working = type("W", (), {"entities": [], "last_topic": ""})()
        self.summary = ""

    def context_block(self):
        return ""


class _MCP:
    tools: ClassVar[list[str]] = [
        "search_documents", "get_document", "get_news", "index_status",
    ]
    tool_specs: ClassVar[list[dict]] = [
        {"name": "search_documents", "description": "search",
         "input_schema": {"properties": {"query": {}, "top_k": {}}}},
        {"name": "get_news", "description": "news",
         "input_schema": {"properties": {"since": {}, "limit": {}}}},
    ]

    def tool_catalog(self, exclude=()):
        return "\n".join(f"- {t}" for t in self.tools if t not in exclude)


def _reply(monkeypatch, payload, is_fallback=False):
    async def fake(system, user, fallback=None, model=None, max_tokens=400):
        result = planner.llm.JsonResult(payload if payload is not None else fallback)
        result.fallback = is_fallback
        return result
    monkeypatch.setattr(planner.llm, "complete_json", fake)


def _explode(monkeypatch):
    async def fake(*a, **kw):
        raise AssertionError("the planner called the model when it should not have")
    monkeypatch.setattr(planner.llm, "complete_json", fake)


@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected", [
    ("你好", Intent.CHITCHAT),
    ("What can you do?", Intent.META),
    ("今天新竹的天氣如何？", Intent.OUT_OF_SCOPE),
])
async def test_non_retrieval_intents_cost_nothing(monkeypatch, message, expected):
    """A greeting must not reach the model at all — these turns are answered
    from a canned string, so there is nothing to plan."""
    _explode(monkeypatch)
    result = await plan(message, _Mem(), _MCP())
    assert result.intent is expected
    assert result.by == "rule"
    assert result.queries == []
    assert result.tool == ""


@pytest.mark.asyncio
async def test_a_knowledge_question_gets_intent_tool_and_queries_from_one_call(monkeypatch):
    _reply(monkeypatch, {
        "intent": "knowledge", "tool": "get_news", "args": {"limit": 3},
        "queries": ["最新消息", "latest news"], "topic": "news",
        "entities": ["AI 中心"], "confidence": 0.9, "reason": "asks for recent items",
    })
    result = await plan("最近有什麼新消息？", _Mem(), _MCP())
    assert result.intent is Intent.KNOWLEDGE
    assert result.tool == "get_news"
    assert result.args == {"limit": 3}
    assert result.queries == ["最新消息", "latest news"]
    assert result.by == "llm"


@pytest.mark.asyncio
async def test_a_hallucinated_tool_falls_back_and_says_so(monkeypatch):
    _reply(monkeypatch, {"intent": "knowledge", "tool": "list_by_section",
                         "args": {"section": "teacher"}, "queries": ["師資"]})
    result = await plan("中心有哪些老師？", _Mem(), _MCP())
    assert result.tool == DEFAULT_TOOL
    assert "list_by_section" in result.note
    # Arguments for a tool that was rejected must not be forwarded.
    assert result.args == {}


@pytest.mark.asyncio
async def test_unknown_intent_label_degrades_to_knowledge(monkeypatch):
    _reply(monkeypatch, {"intent": "banana", "tool": DEFAULT_TOOL, "queries": ["x"]})
    assert (await plan("?", _Mem(), _MCP())).intent is Intent.KNOWLEDGE


@pytest.mark.asyncio
async def test_a_failed_call_reports_the_fallback_honestly(monkeypatch):
    """Reporting a deterministic fallback as an LLM decision is how a trace
    panel starts lying about what actually ran."""
    _reply(monkeypatch, None, is_fallback=True)
    result = await plan("What credit programs does TAICA offer?", _Mem(), _MCP())
    assert result.by == "llm-fallback"
    assert result.tool == DEFAULT_TOOL
    # The deterministic rewrite still supplies a Chinese variant, which is the
    # whole reason an English question retrieves anything here.
    assert any("學分學程" in q for q in result.queries)


@pytest.mark.asyncio
async def test_queries_are_deduped_capped_and_never_empty(monkeypatch):
    _reply(monkeypatch, {"intent": "knowledge", "tool": DEFAULT_TOOL,
                         "queries": ["a", "a", " ", "b", "c", "d"]})
    assert (await plan("q", _Mem(), _MCP())).queries == ["a", "b", "c"]

    _reply(monkeypatch, {"intent": "knowledge", "tool": DEFAULT_TOOL, "queries": []})
    assert (await plan("算力申請", _Mem(), _MCP())).queries == ["算力申請"]


@pytest.mark.asyncio
async def test_model_intent_wins_over_the_rule_but_the_disagreement_is_recorded(monkeypatch):
    # The rule sees in-scope vocabulary and says KNOWLEDGE; the model has the
    # conversation and can tell this continues an earlier thread.
    _reply(monkeypatch, {"intent": "follow_up", "tool": DEFAULT_TOOL, "queries": ["x"]})
    result = await plan("學分學程要修幾學分？", _Mem(turns=2), _MCP())
    assert result.intent is Intent.FOLLOW_UP
    assert "rule said knowledge" in result.note


def test_normalise_args_drops_undeclared_keys():
    spec = {"name": "get_news", "input_schema": {"properties": {"since": {}, "limit": {}}}}
    assert normalise_args("get_news", {"limit": 3, "bogus": 1}, spec) == {"limit": 3}
    assert normalise_args("get_news", {"limit": 3}, None) == {}


def test_turn_plan_defaults_are_safe():
    assert TurnPlan(intent=Intent.KNOWLEDGE).tool == DEFAULT_TOOL

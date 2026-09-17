"""Intent rules must hold without a model — every rule hit is one LLM call saved."""

import pytest

from src.client.intent import Intent, classify_by_rule
from src.client.memory import ConversationMemory
from src.client.router import get_canned, route


class _Mem(ConversationMemory):
    def __init__(self, turns=0):
        self.turns = ["x"] * turns
        self.working = type("W", (), {"entities": [], "last_topic": ""})()
        self.summary = ""


@pytest.mark.parametrize(
    "message,expected",
    [
        ("你好", Intent.CHITCHAT),
        ("thanks!", Intent.CHITCHAT),
        ("good morning", Intent.CHITCHAT),
        ("你的資料來源是什麼？", Intent.META),
        ("How does this work?", Intent.META),
        ("今天新竹的天氣如何？", Intent.OUT_OF_SCOPE),
        ("TAICA 有哪些學分學程？", Intent.KNOWLEDGE),
        ("實驗室有哪些設備？", Intent.KNOWLEDGE),
        # The live site's own vocabulary, which the corpus is now mostly about.
        ("算力申請需要什麼條件？", Intent.KNOWLEDGE),
        ("GPU 平台有幾張卡？", Intent.KNOWLEDGE),
        # The four questions offered as sample buttons in the English UI. A rule
        # hit on an off-topic or chitchat message now saves the entire turn, not
        # just one call: those intents never reach the planner at all.
        ("What do I need to apply for compute time?", Intent.KNOWLEDGE),
        ("What credit programs does TAICA offer?", Intent.KNOWLEDGE),
        ("What's the latest news from the centre?", Intent.KNOWLEDGE),
        ("What's the weather like in Hsinchu today?", Intent.OUT_OF_SCOPE),
    ],
)
def test_rules_classify_without_an_llm(message, expected):
    assert classify_by_rule(message, _Mem()).intent is expected


def test_credit_is_not_read_as_the_pronoun_it():
    """"it" used to match inside "cred(it)", so the first English sample button
    was classified FOLLOW_UP on every turn after the first."""
    result = classify_by_rule("What credit programs does TAICA offer?", _Mem(turns=2))
    assert result.intent is Intent.KNOWLEDGE


def test_english_words_do_not_smuggle_in_scope_vocabulary():
    """"AI" used to match inside "av(ai)lable", which suppressed the off-topic
    rule (it only fires when no in-scope term is present)."""
    assert classify_by_rule("Is that movie available tonight?", _Mem()).intent is Intent.OUT_OF_SCOPE


def test_anaphora_needs_prior_context():
    assert classify_by_rule("那個呢？", _Mem(turns=0)) is None
    assert classify_by_rule("那個呢？", _Mem(turns=2)).intent is Intent.FOLLOW_UP


def test_ai_course_question_beats_the_offtopic_pattern():
    # "課程" is in-scope vocabulary; "電影" alone would be out of scope.
    assert classify_by_rule("AI 課程和電影推薦有關嗎？", _Mem()).intent is Intent.KNOWLEDGE


def test_knowledge_and_follow_up_share_the_retrieval_pipeline():
    # tool_selector is gone: the planner decides the tool in the same call that
    # decides intent, so the pipeline is the two stages that do the work.
    assert [a.name for a in route(Intent.KNOWLEDGE)] == ["retrieval", "answer"]
    assert route(Intent.FOLLOW_UP) == route(Intent.KNOWLEDGE)


def test_non_retrieval_intents_have_a_canned_reply():
    for intent in (Intent.CHITCHAT, Intent.META, Intent.OUT_OF_SCOPE):
        assert route(intent) == []
        assert get_canned(intent, "en")
        assert get_canned(intent, "zh")

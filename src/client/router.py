"""Router: intent -> ordered subagent pipeline.

A table, not a chain of ifs. Adding a capability means adding a row, and the
routing decision stays inspectable — which is exactly what gets shown in the
trace panel during the demo.
"""

from src.client.agents.answer_agent import AnswerAgent
from src.client.agents.base import Subagent
from src.client.agents.retrieval_agent import RetrievalAgent
from src.client.intent import Intent

# Tool selection used to be a pipeline stage of its own. It is now decided in
# the planner call, alongside intent and the search queries, so the pipeline is
# the two stages that actually do work.
_RETRIEVAL_PIPELINE: list[Subagent] = [RetrievalAgent(), AnswerAgent()]

ROUTES: dict[Intent, list[Subagent]] = {
    Intent.KNOWLEDGE: _RETRIEVAL_PIPELINE,
    Intent.FOLLOW_UP: _RETRIEVAL_PIPELINE,
    Intent.CHITCHAT: [],
    Intent.META: [],
    Intent.OUT_OF_SCOPE: [],
}

CANNED: dict[str, dict[Intent, str]] = {
    "zh": {
        Intent.CHITCHAT: (
            "你好，我可以回答元智大學 AI 中心的相關問題：算力申請、TAICA 學分學程、"
            "服務團隊與最新消息，以及網站改版前留下的課程、實驗室、設備與師資資料。"
            "想從哪一項開始？"
        ),
        Intent.META: (
            "我是建立在 MCP 架構上的問答系統。檢索由一台 MCP server 負責，"
            "資料來源是元智大學 AI 中心網站；對話管理、記憶與代理調度在 client 端。"
            "索引包含現行網站的內容，也保留了改版前的既有資料；每個答案都會附上可點擊的"
            "來源連結，全部指向 ai.yzu.edu.tw 本身——現行內容連到其確切頁面，"
            "已無對應頁面的既有資料則連到中心現行首頁。"
        ),
        Intent.OUT_OF_SCOPE: (
            "這個問題超出我的知識範圍。我只涵蓋元智大學 AI 中心網站的內容："
            "現行的算力申請、TAICA 學分學程、服務團隊與最新消息，"
            "以及網站改版前留下的課程、實驗室、設備與師資資料。"
        ),
    },
    "en": {
        Intent.CHITCHAT: (
            "Hello! I can answer questions about the Yuan Ze University AI Center: HPC compute "
            "applications, TAICA credit programs, the service team, and news — plus course, lab, "
            "equipment and faculty content kept from before the site was rebuilt. Where would "
            "you like to start?"
        ),
        Intent.META: (
            "I am a question-answering system built on the MCP architecture. "
            "Retrieval is handled by an MCP server over the Yuan Ze University AI Center website; "
            "conversation management, memory, and agent orchestration run on the client side. "
            "The index covers the current site plus older content kept from before it was "
            "rebuilt. Every answer includes clickable source links that all resolve on "
            "ai.yzu.edu.tw itself — current content links to its exact page, and older content "
            "with no live page links to the centre's current home page instead."
        ),
        Intent.OUT_OF_SCOPE: (
            "This question is outside my knowledge scope. I only cover the Yuan Ze University "
            "AI Center website: HPC compute applications, TAICA credit programs, the service "
            "team and news, plus course, lab, equipment and faculty content kept from before "
            "the site was rebuilt."
        ),
    },
}


def get_canned(intent: Intent, lang: str = "en") -> str:
    """Return the canned response for the given intent and language."""
    lang_dict = CANNED.get(lang, CANNED["en"])
    return lang_dict.get(intent, CANNED["en"][Intent.OUT_OF_SCOPE])


def route(intent: Intent) -> list[Subagent]:
    return ROUTES.get(intent, _RETRIEVAL_PIPELINE)

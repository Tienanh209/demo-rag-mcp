"""Intent vocabulary and the rule fast-path.

A rule catches greetings, meta questions and obvious out-of-scope topics in
~0 ms and 0 tokens. Classifying every "你好" with an LLM call is the easy way to
make a demo feel slow and cost money for nothing.

The rules decide alone only for the three intents that need no retrieval — those
turns are answered from a canned string, so the whole turn costs nothing.
Anything that might need the corpus goes to src/client/planner.py, which settles
intent, tool and search queries in a single call; the rule's verdict is passed
along as a hint rather than thrown away.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from src.client.memory import ConversationMemory


class Intent(StrEnum):
    KNOWLEDGE = "knowledge"        # answerable from the AI Center corpus
    FOLLOW_UP = "follow_up"        # depends on previous turns
    CHITCHAT = "chitchat"          # greetings, thanks, small talk
    META = "meta"                  # questions about the system itself
    OUT_OF_SCOPE = "out_of_scope"  # unrelated to the AI Center


@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    reason: str
    entities: list[str]
    by: str = "rule"


# Each pattern is two alternations: CJK terms, which must keep matching as bare
# substrings because Chinese is written without spaces, and Latin terms wrapped in
# \b. Without those boundaries "it" matched inside "cred(it)" and sent every
# English question about credit programs down the follow-up path, while "AI" and
# "lab" matched inside "av(ai)lable" and "sy(lab)us". \b cannot be applied to the
# CJK side: it requires a non-word character before the term and so fails on 有學程.
_GREETING = re.compile(
    r"^\s*(?:hi there|hello|hey|hi|good (?:morning|afternoon|evening)"
    r"|thank you|thanks a lot|thanks|thx|bye|see you"
    r"|你好|您好|哈囉|嗨|謝謝|感謝|再見|掰掰)"
    r"[!！。.、\s]*$",
    re.IGNORECASE,
)
_META = re.compile(
    r"(?:你是誰|妳是誰|你能做什麼|你會什麼|你怎麼運作|資料來源|知識庫|你的來源)"
    r"|\b(?:what can you do|who are you|what are you|how do you work|how does this work"
    r"|data sources?|knowledge base|where do you get|what do you know)\b",
    re.IGNORECASE,
)
_ANAPHORA = re.compile(
    r"(?:那個|這個|它|他們|上面|剛剛|前面|再說|還有呢|那呢|那.{0,4}呢|呢[?？]?$)"
    r"|\b(?:it|that one|those|they|them|the second|the first|the other one|what about)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE = re.compile(
    r"(?:天氣|氣溫|下雨|股票|股價|匯率|樂透|食譜|怎麼煮|籃球|足球|電影|明星)"
    r"|\b(?:weather|stocks?|stock price|recipes?|cook|football|basketball|movies?|films?"
    r"|restaurants?|lottery|politics)\b",
    re.IGNORECASE,
)
# Vocabulary that reliably belongs to this corpus.
_IN_SCOPE = re.compile(
    r"(?:學程|課程|學分|實驗室|設備|儀器|師資|老師|教師|中心|人工智慧|元智"
    r"|聯絡|電話|信箱|消息|活動|研究"
    # The rebuilt site's own vocabulary. Without these, "算力申請要準備什麼"
    # matched no rule and took the slow path on the most likely question a
    # visitor now asks.
    r"|算力|申請|平台|運算|主任|團隊|高速)"
    r"|\b(?:programs?|courses?|credits?|labs?|laborator(?:y|ies)|equipment"
    r"|contacts?|news|teachers?|facult(?:y|ies)|staff|professors?|cent(?:er|re)"
    r"|e-?mails?|phones?|research|events?|TAICA|AI|YZU|ICAIA"
    r"|GPUs?|HPC|comput(?:e|ing)|apply|application)\b",
    re.IGNORECASE,
)

def classify_by_rule(message: str, memory: ConversationMemory) -> IntentResult | None:
    """Return a decision only when the rules are confident. None means 'ask the model'."""
    if _GREETING.match(message):
        return IntentResult(Intent.CHITCHAT, 0.99, "greeting pattern", [])
    if _META.search(message):
        return IntentResult(Intent.META, 0.92, "meta pattern", [])
    if _OUT_OF_SCOPE.search(message) and not _IN_SCOPE.search(message):
        return IntentResult(Intent.OUT_OF_SCOPE, 0.88, "off-topic vocabulary", [])
    if memory.turns and _ANAPHORA.search(message) and len(message) < 40:
        return IntentResult(Intent.FOLLOW_UP, 0.85, "anaphora with prior context", [])
    if _IN_SCOPE.search(message):
        return IntentResult(Intent.KNOWLEDGE, 0.80, "in-scope vocabulary", [])
    return None

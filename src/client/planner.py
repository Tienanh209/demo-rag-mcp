"""One call decides the whole route.

Intent, tool choice and query rewriting used to be three separate LLM requests,
run back to back before a single passage had been retrieved. They are all the
same kind of decision — read the message, decide how to look things up — and
they were all being asked of the big generation model. A knowledge turn cost
four sequential requests.

They are now one request to a small model (ROUTER_MODEL), which returns intent,
tool, arguments and search queries together. Generation still uses the large
model, because writing a grounded answer is the part that needs it.

The rule fast-path in intent.py is kept, but narrowed to what it is actually
good for: a greeting, a question about the assistant, or an obviously off-topic
message needs no corpus at all, so those turns still cost zero tokens. When the
rules recognise something answerable they do not skip the call — queries and a
tool are still needed — but their verdict rides along as a hint.
"""

from dataclasses import dataclass, field
from typing import Any

from src.client import llm
from src.client.intent import Intent, classify_by_rule
from src.client.memory import ConversationMemory

DEFAULT_TOOL = "search_documents"

# index_status is a health check and get_document is a follow-up on a passage
# already in hand; neither answers a user's question from a standing start.
NOT_FOR_ANSWERING = ("index_status", "get_document")

# The three intents the rules may settle alone. Each is answered from a canned
# string, so there is nothing for the planner to plan.
_NO_RETRIEVAL = (Intent.CHITCHAT, Intent.META, Intent.OUT_OF_SCOPE)

_SYSTEM = """You plan one turn for a retrieval assistant that knows the Yuan Ze
University AI Center (元智大學 人工智慧教學與應用發展中心).

The corpus has two halves and BOTH are in scope:
  current  - the centre today: HPC/算力申請 compute applications, the H200 GPU
             platform, the service team (服務團隊), recent news
  archived - the retired site, captured before it was rebuilt: TAICA 學分學程
             credit programs, 課程, 實驗室, 設備, 師資

Decide three things at once.

1. intent — one of:
     knowledge     a factual question the corpus could answer
     follow_up     refers to something earlier in the conversation
     chitchat      greeting, thanks, small talk
     meta          about the assistant itself, its sources or capabilities
     out_of_scope  unrelated to the AI Center

2. tool — which retrieval tool this turn needs:
{catalog}
   Default to search_documents; it handles any question about content.
   Choose get_news only for "latest / recent / what's new" questions, where date
   order matters more than keyword relevance.
   Supply only arguments the tool declares. Omit optional ones you do not need.

3. queries — 1-3 search strings for the retrieval call.
   Resolve pronouns and ellipsis using the conversation context.
   The corpus is written in Traditional Chinese. ALWAYS include at least one
   Chinese query no matter which language the user wrote in — an English query
   alone barely separates relevant from irrelevant here.
   Keep each query short: under 20 Chinese characters or 10 English words.

Return:
{{"intent": "...", "tool": "...", "args": {{...}}, "queries": ["...", "..."],
  "topic": "short topic label", "entities": ["..."], "confidence": 0.0,
  "reason": "one short sentence"}}
entities = named things worth remembering (program names, lab names, dates)."""


@dataclass
class TurnPlan:
    """Everything the pipeline needs to know before it touches the corpus."""

    intent: Intent
    confidence: float = 0.5
    reason: str = ""
    entities: list[str] = field(default_factory=list)
    tool: str = DEFAULT_TOOL
    args: dict[str, Any] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    topic: str = ""
    by: str = "rule"
    note: str = ""  # trace-only: how the plan was corrected, if it was


def normalise_args(tool: str, args: dict, spec: dict | None) -> dict:
    """Drop arguments the tool does not declare, so a stray key cannot fail the call."""
    props = ((spec or {}).get("input_schema") or {}).get("properties", {})
    if not props:
        return {}
    return {k: v for k, v in args.items() if k in props}


async def plan(message: str, memory: ConversationMemory, mcp: Any) -> TurnPlan:
    # Import here: retrieval_agent imports DEFAULT_TOOL from this module.
    from src.client.agents.retrieval_agent import rewrite_fallback

    ruled = classify_by_rule(message, memory)
    if ruled is not None and ruled.intent in _NO_RETRIEVAL:
        return TurnPlan(
            intent=ruled.intent,
            confidence=ruled.confidence,
            reason=ruled.reason,
            tool="",
            by="rule",
        )

    available = list(getattr(mcp, "tools", []))
    catalog = mcp.tool_catalog(exclude=NOT_FOR_ANSWERING) if available else ""

    # Built before the call, from the deterministic paths that already exist, so
    # a failed request degrades the plan instead of failing the turn.
    deterministic = rewrite_fallback(message, memory)
    fallback = {
        "intent": str(ruled.intent) if ruled else str(Intent.KNOWLEDGE),
        "tool": DEFAULT_TOOL,
        "args": {},
        "queries": deterministic["queries"],
        "topic": deterministic["topic"],
        "entities": [],
        "confidence": ruled.confidence if ruled else 0.4,
        "reason": ruled.reason if ruled else "planner fallback",
    }

    hint = f"\n\n[Rule hint] {ruled.intent} ({ruled.reason})" if ruled else ""
    user = f"{memory.context_block()}{hint}\n\n[New message]\n{message}"
    data = await llm.complete_json(
        _SYSTEM.format(catalog=catalog or "  (no tools advertised)"),
        user,
        fallback=fallback,
        model=llm.router_model(),
    )

    try:
        intent = Intent(data.get("intent", Intent.KNOWLEDGE))
    except ValueError:
        intent = Intent.KNOWLEDGE

    note = ""
    tool = str(data.get("tool") or DEFAULT_TOOL)
    # A hallucinated tool name is the obvious failure here, so the choice is
    # checked against what the server actually advertised.
    if tool not in available or tool in NOT_FOR_ANSWERING:
        if tool != DEFAULT_TOOL:
            note = f"rejected unknown tool {tool!r}"
        tool = DEFAULT_TOOL

    raw_args = data.get("args")
    spec = next((s for s in getattr(mcp, "tool_specs", []) if s["name"] == tool), None)
    args = normalise_args(tool, raw_args if isinstance(raw_args, dict) else {}, spec)

    queries = [q.strip() for q in data.get("queries", []) if isinstance(q, str) and q.strip()]
    queries = list(dict.fromkeys(queries))[:3] or [message]

    # The rules and the model can legitimately disagree — the model saw the
    # conversation, the rules only saw this message — so the model wins. The
    # disagreement is still worth showing; it is the interesting part of a trace.
    if ruled is not None and ruled.intent != intent:
        note = (note + "; " if note else "") + f"rule said {ruled.intent}"

    return TurnPlan(
        intent=intent,
        confidence=float(data.get("confidence", 0.5) or 0.5),
        reason=str(data.get("reason", "")),
        entities=[str(e) for e in data.get("entities", [])][:6],
        tool=tool,
        args=args,
        queries=queries,
        topic=str(data.get("topic", "")),
        # A silent fallback reported as an LLM decision is how a trace panel
        # starts lying about what actually ran.
        by="llm-fallback" if data.fallback else "llm",
        note=note,
    )

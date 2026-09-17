"""Retrieval subagent.

Two jobs the naive version skips:

1. Query rewriting. "那個學程要修幾學分?" retrieves nothing on its own. Resolved
   against memory it becomes "人工智慧視覺技術學分學程 學分", which does.
2. Multi-query. One question often has two lexical framings (the Chinese
   official name and an English or abbreviated form). Issuing both and fusing
   the results lifts recall on this corpus.

Neither happens here any more: the planner settles the queries and the tool in
the same call that settles intent, so this agent executes a plan rather than
making one. `rewrite_fallback` stays here, next to the vocabulary it uses, and
is what the planner falls back to when its own call fails.
"""

import asyncio
import re

from src.client.agents.base import AgentContext, AgentResult, Subagent
from src.client.memory import ConversationMemory
from src.client.planner import DEFAULT_TOOL, TurnPlan, normalise_args
from src.common.config import settings

# Below this many characters a top passage probably got cut mid-answer, so it is
# worth one get_document call to read the whole page.
_DEEP_READ_BELOW = 300
_DEEP_READ_LIMIT = 1500


def _row_text(row: dict) -> str:
    """Render a listing record as the sentence a reader would want."""
    parts = [row.get("date", ""), row.get("title", "")]
    if row.get("section"):
        parts.append(f"({row['section']})")
    return " ".join(p for p in parts if p).strip()

_ANAPHORA = re.compile(
    r"(?:那個|這個|它|他們|上面|剛剛|前面|那.{0,4}呢)|\b(?:it|that|those)\b", re.IGNORECASE
)

# An English question retrieves badly against a Chinese corpus: the lexical arm
# finds no overlap at all, and the dense arm barely separates relevant from
# irrelevant (measured: every English question lands in 0.77-0.84, relevant or
# not). The LLM rewrite normally supplies a Chinese variant and the scores jump
# to 0.90+. This map is the safety net for when that one call fails.
_EN_TO_ZH = {
    "credit program": "學分學程", "programme": "學分學程", "program": "學分學程",
    "credits": "學分", "credit": "學分", "course": "課程", "curriculum": "課程",
    "teacher": "師資 老師", "faculty": "師資", "professor": "教師", "staff": "師資",
    "news": "最新消息", "announcement": "公告", "event": "活動",
    "lab": "實驗室", "laboratory": "實驗室", "equipment": "設備", "instrument": "儀器",
    "contact": "聯絡方式", "email": "信箱", "phone": "電話",
    "research": "研究", "centre": "中心", "center": "中心",
}


def chinese_terms(message: str) -> str:
    """Chinese search terms for the English words in a message.

    Longest key first so "credit program" wins before "program" can match it.
    """
    low = message.lower()
    hits = [zh for en, zh in sorted(_EN_TO_ZH.items(), key=lambda kv: -len(kv[0])) if en in low]
    return " ".join(dict.fromkeys(hits))


def rewrite_fallback(message: str, memory: ConversationMemory) -> dict:
    """Deterministic rewriting, used when the planner call fails.

    Splices in remembered context when the message cannot stand alone, and adds a
    Chinese variant when the message is English.

    Takes the memory rather than an AgentContext because the planner runs before
    any context object exists.
    """
    queries = [message]
    if _ANAPHORA.search(message) or len(message) < 12:
        anchor = memory.working.last_topic or (
            memory.working.entities[-1] if memory.working.entities else ""
        )
        if anchor:
            stripped = _ANAPHORA.sub("", message).strip(" ?？的呢")
            queries.insert(0, f"{anchor} {stripped}".strip())
    zh = chinese_terms(message)
    if zh:
        queries.insert(0, zh)
    return {"queries": queries[:3], "topic": memory.working.last_topic or message[:24]}


class RetrievalAgent(Subagent):
    name = "retrieval"

    async def run(self, ctx: AgentContext) -> AgentResult:
        turn_plan: TurnPlan = ctx.scratch["plan"]
        queries = turn_plan.queries or [ctx.message]
        tool = turn_plan.tool or DEFAULT_TOOL

        if tool == DEFAULT_TOOL:
            passages = await self._search(ctx, queries)
        else:
            passages = await self._direct_tool(ctx, tool, turn_plan.args)
            if not passages:
                # A listing tool can legitimately come back empty (wrong section,
                # no news since that date). Falling back to search beats telling
                # the user nothing exists.
                with ctx.trace.step("router:fallback", f"{tool} returned nothing"):
                    pass
                passages = await self._search(ctx, queries)

        await self._deep_read(ctx, passages)

        ctx.scratch["passages"] = passages
        ctx.scratch["topic"] = turn_plan.topic
        ctx.scratch["grounded"] = bool(passages) and passages[0]["score"] >= settings.min_score

        return AgentResult(
            answer="",
            citations=_cite(passages),
            grounded=ctx.scratch["grounded"],
        )

    @staticmethod
    async def _search(ctx: AgentContext, queries: list[str]) -> list[dict]:
        """The multi-query path: fan out, then fuse by best score per passage."""
        with ctx.trace.step("mcp:search_documents", "calling server") as step:
            responses = await asyncio.gather(
                *(
                    ctx.mcp.call("search_documents", query=q, top_k=settings.top_k_final)
                    for q in queries
                )
            )
            merged: dict[str, dict] = {}
            for resp in responses:
                for item in resp.get("results", []):
                    key = item["url"] + "|" + item["text"][:60]
                    if key not in merged or item["score"] > merged[key]["score"]:
                        merged[key] = item
            passages = sorted(merged.values(), key=lambda r: r["score"], reverse=True)
            passages = passages[: settings.top_k_final]
            step.detail = f"{len(passages)} passage(s) from {len(queries)} call(s)"
            step.payload = {
                "top_score": passages[0]["score"] if passages else 0.0,
                "threshold": settings.min_score,
                "matched_by": [p.get("matched_by") for p in passages],
            }
        return passages

    @staticmethod
    async def _direct_tool(ctx: AgentContext, tool: str, args: dict) -> list[dict]:
        """Call a non-search tool and shape its rows like passages.

        Listing tools return records, not scored passages, so they are given a
        score of 1.0: the tool was chosen deliberately for this question, and
        putting a relevance score on a date-ordered lookup would only feed a
        meaningless number to the grounding gate.
        """
        spec = next((s for s in ctx.mcp.tool_specs if s["name"] == tool), None)
        with ctx.trace.step(f"mcp:{tool}", "calling server") as step:
            payload = await ctx.mcp.call(tool, **normalise_args(tool, args, spec))
            rows = payload.get("items") or payload.get("documents") or []
            usable = [
                r for r in rows
                if isinstance(r, dict) and (r.get("url") or r.get("cite_url"))
            ]
            passages = [
                {
                    "title": r.get("title", ""),
                    "heading": "",
                    "url": r.get("url", ""),
                    "cite_url": r.get("cite_url", r.get("url", "")),
                    "status": r.get("status", "live"),
                    "text": _row_text(r),
                    "score": 1.0,
                    "matched_by": f"tool:{tool}",
                }
                for r in usable
            ][: settings.top_k_final]
            step.detail = f"{len(passages)} record(s)"
            step.payload = {
                "args": args,
                "returned": len(rows),
                # A row with no URL at all would render as a chip linking to
                # nowhere. Dropping it is cheap; noticing it later is not.
                "skipped_no_url": len(rows) - len(usable),
                "keys": list(payload)[:6],
            }
        return passages

    @staticmethod
    async def _deep_read(ctx: AgentContext, passages: list[dict]) -> None:
        """Expand the top passage when it is too short to answer from.

        Capped at one call: this exists to rescue a truncated best match, not to
        pull whole pages into the prompt.
        """
        if not passages:
            return
        top = passages[0]
        if len(top.get("text", "")) >= _DEEP_READ_BELOW or top["score"] < settings.min_score:
            return
        with ctx.trace.step("mcp:get_document", "expanding a short passage") as step:
            doc = await ctx.mcp.call("get_document", url=top["url"])
            full = doc.get("text", "")
            if not full:
                step.detail = "not indexed, kept the passage"
                return
            before = len(top["text"])
            top["text"] = full[:_DEEP_READ_LIMIT]
            step.detail = f"{before} -> {len(top['text'])} chars"
            step.payload = {"url": top["url"], "expanded_from": before, "to": len(top["text"])}

    @staticmethod
    def format_passages(passages: list[dict]) -> str:
        return "\n\n".join(
            # The status goes inside the metadata parenthetical, not next to the
            # title as "[archived]": a bracketed token is the exact shape of the
            # [n] citation markers the model is told to emit, and it echoed the
            # tag straight into its prose ("根據[archived]資料...").
            f"[{i}] (score {p['score']}"
            + (", archived" if p.get("status", "live") != "live" else "")
            + f") {p['title']}"
            + (f" > {p['heading']}" if p.get("heading") else "")
            # cite_url, not url: the identity URL of an archived page is a 404,
            # and models do echo these into prose. The prompt tells it not to,
            # but if one leaks through it should at least resolve.
            + (f"\nURL: {p['cite_url']}" if p.get("cite_url") else "")
            + f"\n{p['text']}"
            for i, p in enumerate(passages, start=1)
        )


def _cite(passages: list[dict]) -> list[dict]:
    """Passages as citation chips.

    `url` is what the user clicks. Every document now carries a `cite_url` that
    resolves on ai.yzu.edu.tw itself — a live page cites its own exact URL, and
    a retired page with no live equivalent cites the centre's current home page
    (never a third-party archive). It can still be empty defensively, in which
    case an empty href would render as a link that silently does nothing, so
    the UI treats a falsy url as "no link" rather than a dead one. `source_url`
    keeps the retired page's own identity for the tooltip and for memory.
    """
    return [
        {
            "n": i,
            "title": p["title"],
            "heading": p.get("heading", ""),
            "url": p.get("cite_url") or "",
            "source_url": p.get("url", ""),
            "status": p.get("status", "live"),
            "score": p["score"],
            "cited": True,
        }
        for i, p in enumerate(passages, start=1)
    ]

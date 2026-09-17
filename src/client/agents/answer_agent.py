"""Answer subagent.

The refusal path is the important part. If the best passage scores below
min_score, the agent declines in control flow — it does not hand weak context to
a model and ask it to be careful. A model given thin context still writes a
confident paragraph; the only reliable place to stop that is before generation.

Generation requires a model. There is no extractive substitute: an answer built
from a Chinese corpus for an English question was unreadable, so a failed
generation says so and shows the sources instead of pretending.
"""

from src.client import llm
from src.client.agents.base import AgentContext, AgentResult, Subagent
from src.client.agents.retrieval_agent import RetrievalAgent, _cite

_SYSTEM_TEMPLATE = """You answer questions about the Yuan Ze University AI Center
(元智大學 人工智慧教學與應用發展中心) using only the numbered passages provided.
The centre was previously called 人工智慧跨域創新應用中心 (ICAIA); older passages use
that name for the same place.

Rules:
- Every factual sentence carries a citation marker like [1] or [2][3].
- Never state anything the passages do not support. No outside knowledge.
- If the passages only partly cover the question, answer the covered part and
  say plainly what is missing.
- A passage whose metadata says "archived" describes the centre as it was before
  its website was rebuilt. You may use it, but say in your own words that it
  comes from archived material rather than presenting it as the centre's current
  offering. Never copy the word from the metadata line into your prose as a tag.
- Do not list, repeat or write out any URL. The interface renders the sources as
  clickable links beside your answer; a URL typed into the reply is redundant at
  best, and several of these pages have been retired and no longer resolve.
- Reply in {lang_label}. {lang_rule}
- Be direct. No preamble, no "based on the provided context"."""

_LANG_LABELS = {"en": "English", "zh": "繁體中文"}

# The UI language is a hard constraint, not a hint. "Reply in 繁體中文" alone let
# Simplified characters through often enough to be visible on a projector, and
# the passages are all Chinese, so an English-mode answer drifts back into
# Chinese without being told not to.
_LANG_RULES = {
    "zh": (
        "Use Traditional Chinese (繁體中文) as written in Taiwan. Never output "
        "Simplified Chinese characters, even when quoting a passage. Keep proper "
        "nouns, email addresses and URLs verbatim."
    ),
    "en": (
        "Reply in English even though the passages are written in Chinese. On "
        "first use, give an English rendering of a Chinese proper noun with the "
        "original in parentheses."
    ),
}

REFUSAL = {
    "zh": (
        "知識庫中找不到能回答這個問題的資料，因此我不做推測。\n\n"
        "目前索引範圍包含元智大學 AI 中心現行網站（算力申請、TAICA 學分學程、服務團隊、"
        "最新消息），以及改版前網站的既有資料（課程、實驗室、設備、師資等，現已無對應的"
        "現行頁面）。若這個主題應該在範圍內，可能是該頁面尚未被收錄。"
    ),
    "en": (
        "No relevant information was found in the knowledge base, so I won't speculate.\n\n"
        "The index covers the Yuan Ze University AI Center's current site (HPC compute "
        "applications, TAICA credit programs, the service team, news) and retired content "
        "from before the site was rebuilt with no live page any more (courses, labs, "
        "equipment, faculty). If this topic should be in scope, the page may not have been "
        "indexed yet."
    ),
}


GENERATION_FAILED = {
    "zh": (
        "找到了相關資料，但產生回答時發生錯誤。以下是來源頁面，可直接查看。"
    ),
    "en": (
        "I found relevant sources but the answer could not be generated. "
        "The source pages are listed below."
    ),
}


class AnswerAgent(Subagent):
    name = "answer"

    async def run(self, ctx: AgentContext) -> AgentResult:
        passages = ctx.scratch.get("passages", [])
        lang = ctx.scratch.get("lang", "en")

        if not ctx.scratch.get("grounded"):
            with ctx.trace.step("subagent:answer", "refused: below grounding threshold") as step:
                step.payload = {
                    "top_score": passages[0]["score"] if passages else 0.0,
                    "min_score": ctx.scratch.get("min_score"),
                }
            return AgentResult(answer=REFUSAL.get(lang, REFUSAL["en"]), citations=[], grounded=False)

        with ctx.trace.step("subagent:answer", f"generating from {len(passages)} passages") as step:
            lang_label = _LANG_LABELS.get(lang, "English")
            system = _SYSTEM_TEMPLATE.format(
                lang_label=lang_label,
                lang_rule=_LANG_RULES.get(lang, _LANG_RULES["en"]),
            )
            prompt = (
                f"{ctx.memory.context_block()}\n\n"
                f"[Passages]\n{RetrievalAgent.format_passages(passages)}\n\n"
                f"[Question]\n{ctx.message}"
            )
            try:
                answer = await llm.complete(system, prompt)
            except Exception as exc:  # noqa: BLE001 - one bad call must not fail the turn
                step.detail = f"generation failed ({type(exc).__name__})"
                step.payload = {"mode": "failed", "error": type(exc).__name__}
                return AgentResult(
                    answer=GENERATION_FAILED.get(lang, GENERATION_FAILED["en"]),
                    citations=_cite(passages),
                    grounded=False,
                )

            # Only what the model actually cited. The old `cited or
            # _cite(passages)` meant a model that forgot its [n] markers turned
            # every retrieved passage into a claimed source of the answer — the
            # one thing a citation is supposed to rule out. An in-between
            # version returned every passage with a cited:true/false flag for
            # the UI to dim — better, but a reader still had to look past four
            # irrelevant chips to find the one the answer actually used.
            # Filtering to the cited subset here means every client (web, CLI,
            # demo script) gets the same, already-correct list for free.
            all_cites = _cite(passages)
            markers = {c["n"] for c in all_cites if f"[{c['n']}]" in answer}
            if markers:
                cites = [c for c in all_cites if c["n"] in markers]
            else:
                # No [n] marker anywhere in the answer. An answer with zero
                # visible sources reads as unfounded, so the passage that
                # passed the grounding gate is still surfaced — marked
                # cited:false, since the model never actually referenced it —
                # rather than showing nothing at all.
                cites = [{**c, "cited": False} for c in all_cites[:1]]
            step.payload = {
                "mode": "generated",
                "answer_chars": len(answer),
                "lang": lang,
                "markers_found": len(markers),
                "passages": len(passages),
            }

        return AgentResult(answer=answer, citations=cites, grounded=True)

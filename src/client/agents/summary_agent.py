"""Summary subagent — the long-term memory writer.

Runs only when the turn count crosses a threshold, folding older turns into a
rolling summary. Without it the prompt grows linearly with the conversation and
eventually either costs too much or overflows.
"""

from src.client import llm
from src.client.agents.base import AgentContext, AgentResult, Subagent

_SYSTEM = """Compress this conversation into a summary of at most 120 characters
of Chinese (or 60 English words).

Keep: what the user is trying to find out, decisions reached, named entities.
Drop: pleasantries, exact wording, anything already answered and closed.
Return the summary text only."""


class SummaryAgent(Subagent):
    name = "summary"

    async def run(self, ctx: AgentContext) -> AgentResult:
        with ctx.trace.step("subagent:summary", "compacting long-term memory") as step:
            previous = f"[Previous summary]\n{ctx.memory.summary}\n\n" if ctx.memory.summary else ""
            try:
                summary = await llm.complete(
                    _SYSTEM, f"{previous}[Transcript]\n{ctx.memory.transcript()}", max_tokens=200
                )
            except Exception as exc:  # noqa: BLE001 - compaction is never worth losing a turn over
                # This runs after the user's answer is already in hand. Letting it
                # raise turned a routine API hiccup into a failed turn.
                step.detail = f"summary skipped ({type(exc).__name__})"
                return AgentResult(answer="", grounded=True)
            ctx.memory.set_summary(summary)
            step.payload = {"summary_chars": len(summary)}
        return AgentResult(answer="", grounded=True)

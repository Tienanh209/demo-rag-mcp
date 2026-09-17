"""The orchestrator: one turn, start to finish.

  classify intent -> route -> run subagents in order -> update memory

Every stage writes to the trace, so the answer and the reasoning path come back
in the same response object. That is what the demo panel renders.
"""

from dataclasses import dataclass, field
from typing import Any

from src.client import llm
from src.client.agents.base import AgentContext, AgentResult
from src.client.agents.summary_agent import SummaryAgent
from src.client.mcp_session import MCPConnection
from src.client.memory import get_memory
from src.client.planner import plan
from src.client.router import get_canned, route
from src.common.config import settings
from src.common.trace import Trace, get_logger

log = get_logger("client.orchestrator")


@dataclass
class TurnResponse:
    answer: str
    intent: str
    grounded: bool
    citations: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "intent": self.intent,
            "grounded": self.grounded,
            "citations": self.citations,
            "trace": self.trace,
            "agents": self.agents,
        }


class Orchestrator:
    def __init__(self, mcp: MCPConnection) -> None:
        self.mcp = mcp
        self.summary_agent = SummaryAgent()

    async def handle(self, session_id: str, message: str, lang: str = "en") -> TurnResponse:
        memory = get_memory(session_id)
        trace = Trace()

        # One request settles intent, tool and search queries. The three stages
        # below are still reported separately because each is a distinct
        # decision and the trace panel is where the routing is meant to be
        # visible — they simply no longer cost three round trips.
        with trace.step("intent", "classifying") as step:
            turn_plan = await plan(message, memory, self.mcp)
            step.detail = f"{turn_plan.intent} ({turn_plan.confidence:.2f}) via {turn_plan.by}"
            step.payload = {
                "reason": turn_plan.reason,
                "entities": turn_plan.entities,
                "model": llm.router_model() if turn_plan.by != "rule" else None,
            }

        pipeline = route(turn_plan.intent)
        with trace.step("router", f"-> {[a.name for a in pipeline] or 'direct reply'}") as step:
            step.payload = {"intent": str(turn_plan.intent),
                            "pipeline": [a.name for a in pipeline]}

        if pipeline:
            detail = f"{turn_plan.by} -> {turn_plan.tool}"
            if turn_plan.note:
                detail += f" ({turn_plan.note})"
            with trace.step("tool", detail) as step:
                step.detail += "  — decided in the planner call, no extra request"
                step.payload = {
                    "available": list(self.mcp.tools),
                    "chosen": {"tool": turn_plan.tool, "args": turn_plan.args},
                    "queries": turn_plan.queries,
                    "topic": turn_plan.topic,
                }

        memory.add("user", message)

        if not pipeline:
            answer = get_canned(turn_plan.intent, lang)
            memory.add("assistant", answer, intent=str(turn_plan.intent))
            memory.working.note(turn_plan.entities, "", [])
            memory.save()
            return TurnResponse(
                answer=answer,
                intent=turn_plan.intent,
                grounded=True,
                trace=trace.as_list(),
                agents=[],
            )

        ctx = AgentContext(message=message, memory=memory, mcp=self.mcp, trace=trace)
        ctx.scratch["min_score"] = settings.min_score
        ctx.scratch["lang"] = lang
        ctx.scratch["plan"] = turn_plan
        result = AgentResult()
        for agent in pipeline:
            result = await agent.run(ctx)

        memory.add(
            "assistant",
            result.answer,
            citations=result.citations,
            grounded=result.grounded,
            intent=str(turn_plan.intent),
        )
        memory.working.note(
            turn_plan.entities,
            ctx.scratch.get("topic", ""),
            # The page's identity, not the link it is cited by: an archived
            # cite_url is not what "we already talked about this page" means —
            # an archived doc's cite_url is the centre's home page, shared by
            # every retired document, which would collapse every "what we
            # talked about" entry onto the same value.
            [c.get("source_url") or c.get("url", "") for c in result.citations],
        )

        # Persist the answered turn before attempting compaction. Summarisation
        # is best-effort and runs after the answer is already in hand, so it must
        # never be able to discard the turn it was triggered by.
        memory.save()

        if memory.needs_summary():
            await self.summary_agent.run(ctx)
            memory.save()

        return TurnResponse(
            answer=result.answer,
            intent=turn_plan.intent,
            grounded=result.grounded,
            citations=result.citations,
            trace=trace.as_list(),
            agents=[a.name for a in pipeline],
        )

"""Every subagent takes the same context object and returns a partial result.

Keeping one narrow interface is what makes the router trivial and what lets a
new subagent be added without touching the orchestrator's control flow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.client.mcp_session import MCPConnection
from src.client.memory import ConversationMemory
from src.common.trace import Trace


@dataclass
class AgentContext:
    message: str
    memory: ConversationMemory
    mcp: MCPConnection
    trace: Trace
    scratch: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    answer: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    grounded: bool = False


class Subagent(ABC):
    name: str = "subagent"

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult: ...

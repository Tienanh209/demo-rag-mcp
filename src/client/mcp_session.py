"""Owns the MCP connection.

Transport matters here. stdio is the usual MCP default, but it requires the
client to spawn the server as a child process — impossible across two Docker
containers. Streamable HTTP is therefore the Compose default, with stdio kept
for the "plug it into Claude Desktop" part of the demo.
"""

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:  # mcp >= 2.0
    from mcp.client.streamable_http import streamable_http_client as http_client
except ImportError:  # mcp 1.x
    from mcp.client.streamable_http import streamablehttp_client as http_client

from src.common.config import ROOT, settings
from src.common.trace import get_logger

log = get_logger("client.mcp")


class MCPConnection:
    """Long-lived session, opened once at app startup."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.tools: list[str] = []
        self.tool_specs: list[dict[str, Any]] = []

    async def connect(self) -> None:
        if settings.mcp_transport == "stdio":
            # sys.executable, not "python": inside a virtualenv the bare name
            # often resolves to a different interpreter without the deps.
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "src.server.app"],
                cwd=str(ROOT),
                env={**os.environ, "MCP_TRANSPORT": "stdio", "PYTHONPATH": str(ROOT)},
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        else:
            streams = await self._stack.enter_async_context(
                http_client(settings.mcp_server_url)
            )
            read, write = streams[0], streams[1]
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listing = await self.session.list_tools()
        # Keep the descriptions and schemas, not just the names. They are what
        # the server tells a client each tool is *for*, and without them nothing
        # downstream can choose between tools — every call site has to hardcode
        # one, which defeats the point of discovery.
        self.tool_specs = [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
                # snake_case in mcp >= 2.0, camelCase in 1.x
                "input_schema": getattr(t, "input_schema", None)
                or getattr(t, "inputSchema", None)
                or {},
            }
            for t in listing.tools
        ]
        self.tools = [t["name"] for t in self.tool_specs]
        log.info("connected via %s, tools: %s", settings.mcp_transport, ", ".join(self.tools))

    def tool_catalog(self, exclude: tuple[str, ...] = ()) -> str:
        """The discovered tools rendered for a prompt: name, args, purpose."""
        lines = []
        for spec in self.tool_specs:
            if spec["name"] in exclude:
                continue
            props = (spec["input_schema"] or {}).get("properties", {})
            required = set((spec["input_schema"] or {}).get("required", []))
            args = ", ".join(
                f"{k}: {v.get('type', 'any')}" + ("" if k in required else " (optional)")
                for k, v in props.items()
            )
            purpose = spec["description"].split("\n")[0]
            lines.append(f"- {spec['name']}({args}) — {purpose}")
        return "\n".join(lines)

    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("MCP session not connected")
        result = await self.session.call_tool(tool, arguments)
        text = "".join(block.text for block in result.content if getattr(block, "text", None))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read one MCP resource. Resources are a primitive the server advertises
        but nothing exercised until the smoke test stopped relying on a tool that
        only existed to report coverage."""
        if self.session is None:
            raise RuntimeError("MCP session not connected")
        result = await self.session.read_resource(uri)
        text = "".join(
            c.text for c in getattr(result, "contents", []) if getattr(c, "text", None)
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    async def close(self) -> None:
        await self._stack.aclose()
        self.session = None

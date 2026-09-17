"""Terminal client — the fallback if the projector, browser or network misbehaves.

Same orchestrator, different surface. Worth having on demo day.
"""

import asyncio

from rich.console import Console
from rich.panel import Panel

from src.client import llm
from src.client.mcp_session import MCPConnection
from src.client.orchestrator import Orchestrator

console = Console()


async def main() -> None:
    llm.require("cli")
    conn = MCPConnection()
    await conn.connect()
    orchestrator = Orchestrator(conn)
    console.print(Panel(f"tools: {', '.join(conn.tools)}", title="MCP connected"))
    console.print(
        "Type a question, /trace to toggle the trace, /en or /zh to switch the "
        "answer language, /quit to exit.\n"
    )

    show_trace = False
    lang = "en"
    try:
        while True:
            try:
                msg = console.input("[bold green]you[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not msg:
                continue
            if msg in {"/quit", "/exit"}:
                break
            if msg == "/trace":
                show_trace = not show_trace
                console.print(f"[dim]trace {'on' if show_trace else 'off'}[/]")
                continue
            if msg in {"/en", "/zh"}:
                lang = msg[1:]
                console.print(f"[dim]answering in {lang}[/]")
                continue

            result = await orchestrator.handle("cli", msg, lang=lang)
            style = "cyan" if result.grounded else "yellow"
            console.print(Panel(result.answer, title=f"{result.intent}", border_style=style))
            for c in result.citations:
                link = c["url"] or "(no archived copy)"
                tag = "" if c.get("status", "live") == "live" else f" [{c.get('status')}]"
                console.print(f"  [dim][{c['n']}][/] {c['title']}{tag} — {link}")
            if show_trace:
                for s in result.trace:
                    console.print(f"  [dim]{s['stage']:26} {s['detail']}  {s['ms']}ms[/]")
            console.print()
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

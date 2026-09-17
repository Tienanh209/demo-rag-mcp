"""End-to-end smoke run: spawns the MCP server over stdio, drives a short
conversation through the orchestrator, and prints the trace.

    python -m scripts.demo

This is what CI would run. It exercises every layer except the browser.
"""

import argparse
import asyncio

from src.client import llm
from src.client.mcp_session import MCPConnection
from src.client.orchestrator import Orchestrator

SCRIPTS = {
    "zh": [
        "你好",
        "算力申請需要什麼條件？",
        "那個平台有幾張 GPU？",
        "TAICA 有哪些學分學程？",
        "今天新竹的天氣如何？",
        "你的資料來源是什麼？",
    ],
    "en": [
        "hello",
        "What do I need to apply for compute time?",
        "How many GPUs does that platform have?",
        "What credit programs does TAICA offer?",
        "What's the weather like in Hsinchu today?",
        "What are your sources?",
    ],
}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # The Chinese script was being answered in English because handle() defaults
    # to lang="en" — the demo was quietly not exercising the language switch at
    # all, which is the one thing the UI toggle promises.
    ap.add_argument("--lang", choices=("zh", "en"), default="zh",
                    help="answer language, matching the console's EN / 中文 toggle")
    args = ap.parse_args()

    conn = MCPConnection()
    await conn.connect()
    orchestrator = Orchestrator(conn)
    print(f"\nMCP tools: {', '.join(conn.tools)}")
    print(f"LLM backend: {llm.backend()}  router model: {llm.router_model()}")
    print(f"answer language: {args.lang}\n" + "=" * 72)

    try:
        for message in SCRIPTS[args.lang]:
            result = await orchestrator.handle(f"smoke-{args.lang}", message, lang=args.lang)
            print(f"\n▸ {message}")
            print(f"  intent={result.intent}  grounded={result.grounded}  agents={result.agents}")
            for line in result.answer.splitlines():
                print(f"  | {line}")
            for c in result.citations:
                mark = "" if c.get("cited", True) else "  (retrieved, not cited)"
                link = c["url"] or "(no archived copy — unlinked)"
                print(f"  [{c['n']}] {c['title']} › {c['heading']}  "
                      f"({c['score']}, {c.get('status', 'live')}){mark}")
                print(f"      {link}")
            for s in result.trace:
                print(f"    · {s['stage']:26} {s['detail']}  {s['ms']}ms")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""MCP server for the YZU AI Center knowledge base.

Exposes all three MCP primitives:
  Tools     - search_documents, get_document, get_news, index_status
  Resources - yzu://doc/{url_id} so any host can read a source page directly
  Prompts   - grounded_answer, a reusable citation-first answering template

The server knows nothing about conversations, memory or LLMs. That separation is
what lets the same process serve our own client, Claude Desktop, or any other
MCP host without modification.
"""

import json
from urllib.parse import unquote

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x, where the same class was called FastMCP
    from mcp.server.fastmcp import FastMCP as MCPServer

from src.common.config import settings
from src.common.trace import get_logger
from src.server import retriever

log = get_logger("server.app")

mcp = MCPServer(
    "yzu-ai-center-rag",
    instructions=(
        "Retrieval over the Yuan Ze University AI Center website "
        "(人工智慧教學與應用發展中心). The index covers the centre's current site — HPC "
        "compute applications, TAICA credit programs, the service team, news — and "
        "retired content from before a 2026 rebuild that has no live page any more "
        "(older news, faculty, equipment). Results carry a status of 'live' or "
        "'archived'; every citation URL resolves on ai.yzu.edu.tw itself — a live "
        "result links to its own page, an archived one links to the centre's "
        "current site since the exact page no longer exists. Archived material "
        "describes the centre before the rebuild and should not be presented as "
        "current without saying so. Four tools: search_documents for any factual "
        "question, get_document to expand one page, get_news for date-ordered "
        "announcements, index_status for a health check."
    ),
    version="0.1.0",
)


@mcp.tool()
def search_documents(query: str, top_k: int = 5) -> str:
    """Search the AI Center knowledge base and return the most relevant passages.

    Args:
        query: A focused search query. Chinese or English both work.
        top_k: How many passages to return (1-10).
    """
    top_k = max(1, min(top_k, 10))
    hits = retriever.search(query, top_k=top_k)
    return json.dumps(
        {
            "query": query,
            "count": len(hits),
            "results": [
                {
                    "rank": i,
                    "score": h.score,
                    "title": h.title,
                    "heading": h.heading,
                    "url": h.url,
                    "cite_url": h.cite_url,
                    "status": h.status,
                    "text": h.text,
                    "matched_by": h.matched_by,
                }
                for i, h in enumerate(hits, start=1)
            ],
        },
        ensure_ascii=False,
    )


@mcp.tool()
def get_document(url: str) -> str:
    """Fetch the full text of one indexed page, given its URL.

    Use after search_documents when a passage is too short to answer confidently.
    """
    doc = retriever.get_document(url)
    if doc is None:
        return json.dumps({"error": "not_indexed", "url": url}, ensure_ascii=False)
    return json.dumps(doc, ensure_ascii=False)


@mcp.tool()
def get_news(since: str = "", limit: int = 5) -> str:
    """List the most recent news and announcements, newest first.

    Prefer this over search_documents for "what's new", "latest news" or
    "recent announcements" — it orders by publication date instead of by
    relevance, which keyword search cannot do.

    Args:
        since: Optional ISO date (YYYY-MM-DD). Only items on or after it.
        limit: How many items to return (1-25).
    """
    items = retriever.news(since=since, limit=limit)
    return json.dumps(
        {"since": since, "count": len(items), "items": items}, ensure_ascii=False
    )


@mcp.tool()
def index_status() -> str:
    """Report index size and retrieval configuration. Useful for health checks."""
    return json.dumps(retriever.status(), ensure_ascii=False)


@mcp.resource("yzu://doc/{url_id}")
def read_doc(url_id: str) -> str:
    """Expose an indexed page as an MCP resource."""
    doc = retriever.get_document(unquote(url_id))
    return doc["text"] if doc else f"Not indexed: {unquote(url_id)}"


@mcp.resource("yzu://index/manifest")
def read_manifest_resource() -> str:
    """The index manifest as a readable resource."""
    return json.dumps({**retriever.status(), "sources": retriever.sources(),
                       "pages": retriever.pages()},
                      ensure_ascii=False, indent=2)


@mcp.prompt()
def grounded_answer(question: str, language: str = "zh-TW") -> str:
    """A citation-first answering template the host can reuse verbatim."""
    return (
        f"Answer the question using only the passages returned by search_documents.\n"
        f"Reply in {language}.\n"
        f"Cite every claim as [n] matching the passage rank, and list the source URLs "
        f"at the end.\n"
        f"If the passages do not contain the answer, say so plainly and do not guess.\n\n"
        f"Question: {question}"
    )


def main() -> None:
    transport = settings.mcp_transport
    log.info("starting MCP server (transport=%s)", transport)
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
        )


if __name__ == "__main__":
    main()

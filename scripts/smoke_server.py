"""Smoke test for the MCP server — no LLM involved.

Run this before touching the client. It verifies the half of the system that has
no external dependencies: transport, handshake, tool discovery, and retrieval.
If this passes, any later failure is in the client or the LLM, which narrows
debugging enormously.

    python -m scripts.smoke_server
"""

import argparse
import asyncio
import json
import sys

from src.client.mcp_session import MCPConnection
from src.common.config import settings

QUESTIONS = [
    "算力申請需要什麼條件？",
    "TAICA 有哪些學分學程？",
    "AI 中心的聯絡方式",
    "最近有什麼新消息",
    "quantum blockchain marketing strategy",  # deliberately unrelated
]

EXPECTED_TOOLS = {"search_documents", "get_document", "get_news", "index_status"}
MANIFEST_URI = "yzu://index/manifest"

# The repo ships a two-page seed corpus. Below these counts the system still
# works; it just has not been pointed at the full site yet, so warn, don't fail.
MIN_DOCS = 15
MIN_CHUNKS = 50


def line(char: str = "-") -> None:
    print(char * 72)


def check_links(pages: list[dict]) -> list[str]:
    """Verify that nothing is cited by a dead link.

    This is the assertion the whole live/archived split exists to satisfy: the
    index once cited 47 pages and 46 of them were 404s, which no test caught
    because nothing ever fetched a citation URL. Every citation — live or
    archived — must resolve on ai.yzu.edu.tw itself: a live page cites its own
    exact URL, and a retired page with no live equivalent cites the centre's
    real home page rather than a third-party archive, so there is exactly one
    domain to ever verify.

    Network-bound and slow, so it runs only under --check-links.
    """
    from urllib.parse import urlparse

    import httpx

    problems: list[str] = []
    checked = {"live": 0, "archived": 0}
    with httpx.Client(timeout=30.0, follow_redirects=True,
                      headers={"User-Agent": "yzu-rag-mcp/0.2 (link check)"}) as client:
        for page in pages:
            status_, url, cite = page.get("status", "live"), page["url"], page.get("cite_url", "")
            if not cite:
                problems.append(f"{url}: status={status_} but no cite_url")
                continue
            if urlparse(cite).netloc != "ai.yzu.edu.tw":
                problems.append(f"{url}: cite_url is not on the real site ({cite})")
                continue
            try:
                resp = client.get(cite)
            except Exception as exc:  # noqa: BLE001 - a failed fetch is a failed link
                problems.append(f"{cite}: {type(exc).__name__}")
                continue
            if resp.status_code >= 400:
                problems.append(f"HTTP {resp.status_code}  {cite}")
            checked[status_] = checked.get(status_, 0) + 1

    print(f"link check: live={checked['live']} archived={checked['archived']} "
          f"(every citation resolves on ai.yzu.edu.tw)")
    if problems:
        print(f"FAIL  {len(problems)} citation link problem(s):")
        for p in problems[:20]:
            print(f"  - {p}")
        return [f"{len(problems)} citation links are broken"]
    print("OK    every citation link resolves, all on the real site")
    return []


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check-links", action="store_true",
                    help="fetch every citation URL and assert it resolves (network, slow)")
    args = ap.parse_args()
    failures: list[str] = []

    print(f"transport : {settings.mcp_transport}")
    print(f"target    : {settings.mcp_server_url}")
    line("=")

    conn = MCPConnection()
    try:
        await conn.connect()
    except Exception as exc:  # noqa: BLE001 - any failure here is a connection failure
        print(f"FAIL  could not connect: {exc}")
        print("\nWith MCP_TRANSPORT=stdio the client spawns the server itself;")
        print("check that `python -m src.server.app` runs without error.")
        return 1

    # --- 1. tool discovery --------------------------------------------------
    print(f"tools discovered: {', '.join(sorted(conn.tools))}")
    missing = EXPECTED_TOOLS - set(conn.tools)
    if missing:
        failures.append(f"missing tools: {missing}")
        print(f"FAIL  missing: {missing}")
    else:
        print(f"OK    all {len(EXPECTED_TOOLS)} expected tools present")
    extra = set(conn.tools) - EXPECTED_TOOLS
    if extra:
        print(f"note  server also advertises: {sorted(extra)}")
    line()

    # --- 2. index status ----------------------------------------------------
    status = await conn.call("index_status")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    chunks = status.get("chunks", 0)
    if chunks == 0:
        failures.append("index is empty")
        print("FAIL  no chunks — run `make ingest`")
    elif chunks < MIN_CHUNKS:
        print(f"WARN  only {chunks} chunks — fine for the seed corpus, thin for a demo.")
        print("      Run `make crawl && make ingest` to index the full site.")
    else:
        print(f"OK    {chunks} chunks indexed")
    line()

    # --- 3. coverage --------------------------------------------------------
    # Read through the resource primitive rather than a tool: coverage is
    # reference data, not an action, and this is the only place resources get
    # exercised at all.
    try:
        manifest = await conn.read_resource(MANIFEST_URI)
    except Exception as exc:  # noqa: BLE001 - degrade to the status we already have
        print(f"WARN  could not read {MANIFEST_URI} ({exc}) — falling back to index_status")
        manifest = status
    pages = manifest.get("pages", [])
    docs = manifest.get("documents", len(pages))
    print(f"documents indexed: {docs}")
    print(f"  live={manifest.get('live', '?')}  archived={manifest.get('archived', '?')}")
    for url in manifest.get("sources", [])[:10]:
        print(f"  {url}")
    if docs == 0:
        failures.append("no documents indexed")
        print("FAIL  no documents")
    elif docs < MIN_DOCS:
        print(f"WARN  {docs} document(s) — seed corpus only; run `make crawl` for full coverage")
    else:
        print(f"OK    {docs} documents")
    line()

    # --- 4. retrieval sanity ------------------------------------------------
    for q in QUESTIONS:
        res = await conn.call("search_documents", query=q, top_k=3)
        results = res.get("results", [])
        print(f"\nquery: {q}")
        if not results:
            print("  (no results)")
            continue
        for r in results:
            heading = f" > {r['heading']}" if r.get("heading") else ""
            print(f"  [{r['rank']}] {r['score']:<7} {r['matched_by']:<8} {r['title']}{heading}")
            print(f"      {r['url']}")

    line()

    # --- 5. citation links --------------------------------------------------
    if args.check_links and pages:
        failures.extend(check_links(pages))
        line()

    print("\nRead the scores above before setting MIN_SCORE.")
    print("The unrelated query should score visibly lower than the real ones.")
    print("If it does not, the threshold cannot separate them and hybrid weighting needs work.")
    line("=")

    await conn.close()

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nServer side is healthy. Move on to the client.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

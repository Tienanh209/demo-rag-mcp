"""Resolve a real, currently-resolving citation URL for every retired document.

The source site was rebuilt in 2026 and every pre-rebuild URL now 404s. The
first fix for this cited the retired pages through the Wayback Machine — but a
citation is supposed to be "click here to see this on the centre's own site",
and web.archive.org is not that, however well it resolves. The correct fix
does not need a third party at all:

    1. Some retired pages turn out to have an exact live equivalent — the BFS
       crawl found a Joomla category (catid=9, TAICA) that nothing on the site
       links to, but which still carries the same 5 credit programs the old
       corpus had. Where a title match confirms this, the retired duplicate is
       retired from the corpus entirely: the live page is strictly better —
       current, real, and it stops the two from competing for rank in
       retrieval (which is what was happening before this ran).
    2. Everything else genuinely has no live page any more. Citing it is still
       useful (it is the only record of TAICA's own account of, say, its lab
       safety notice), but the link has to point at something on the real
       domain that actually exists today. That is the centre's own home page —
       not a page that merely mentions the topic (which would be a citation
       that looks specific but points at the wrong thing), but the one page on
       the real site that is always true to link to.

Run once, offline, deterministic — no network calls, no rate limits, nothing
to cache. Re-run any time the live corpus changes; it is idempotent.
"""

import argparse
import json

from src.common.config import settings
from src.common.trace import get_logger

log = get_logger("resolve_sources")

HOME_URL = "https://ai.yzu.edu.tw/index.php/tw"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    paths = sorted(settings.raw_dir.glob("*.json"))
    if not paths:
        raise SystemExit(f"No documents in {settings.raw_dir}.")

    docs = [(p, json.loads(p.read_text(encoding="utf-8"))) for p in paths]
    live_titles = {d["title"] for _, d in docs if d.get("status") == "live"}

    retire: list[tuple] = []
    fallback: list[tuple] = []
    for path, doc in docs:
        if doc.get("status") not in ("archived", "archived_unavailable"):
            continue
        if doc["title"] in live_titles:
            retire.append((path, doc))
        else:
            fallback.append((path, doc))

    log.info("%d retired duplicate(s) — a live page now covers the same content:",
             len(retire))
    for path, doc in retire:
        log.info("  %s  (%s)", doc["url"], doc["title"][:40])

    log.info("%d document(s) with no live page — citing the real home page:",
             len(fallback))

    if args.apply:
        for path, _doc in retire:
            path.unlink()
        for path, doc in fallback:
            doc["status"] = "archived"
            doc["cite_url"] = HOME_URL
            doc["archived_at"] = ""
            path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        log.info("applied: %d file(s) removed, %d file(s) updated",
                 len(retire), len(fallback))
    else:
        log.info("dry run — pass --apply to write changes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

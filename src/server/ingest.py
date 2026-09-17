"""Build the index from data/raw/*.json.

Chunking is heading-aware first, then length-bounded. The document title and
heading are prepended to every chunk so a retrieved fragment keeps its own
context — a passage that arrives as "本聯盟各學分學程總修習學分為 15 學分" is
ambiguous; "TAICA聯盟學分學程介紹 > 人工智慧視覺技術學分學程" in front of it is not.
"""

import argparse
import hashlib
import json
import re
from typing import Any

from src.common.config import settings
from src.common.trace import get_logger
from src.server.store import dense_available, embed, reset_cache, save_index

log = get_logger("server.ingest")

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$", re.MULTILINE)
# News and notice pages lead with their publication date; get_news orders on it.
DATE_RE = re.compile(r"\b(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})\b")


def extract_date(text: str) -> str:
    """ISO date from the head of a page, or '' when it carries none."""
    m = DATE_RE.search(text[:300])
    if not m:
        return ""
    year, month, day = m.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def load_documents() -> list[dict[str, Any]]:
    docs = []
    for path in sorted(settings.raw_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("text", "").strip():
            docs.append(payload)
    log.info("loaded %d documents from %s", len(docs), settings.raw_dir)
    return docs


def split_sections(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs. Text before the first heading gets ''."""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("", text[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(2).strip(), text[m.end() : end]))
    return sections


def window(body: str, size: int, overlap: int) -> list[str]:
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) <= size:
        return [body] if body else []
    out, start = [], 0
    while start < len(body):
        end = min(start + size, len(body))
        if end < len(body):
            for sep in ("\n\n", "。", "！", "？", "\n", ". "):
                cut = body.rfind(sep, start + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        piece = body[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(body):
            break
        start = max(end - overlap, start + 1)
    return out


def chunk_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = []
    # The crawler reads the date out of the page's own <time> markup, which is
    # the only place the rebuilt site carries it. The regex stays as the
    # fallback for the archived corpus, whose pages do lead with their date.
    date = doc.get("date") or extract_date(doc["text"])
    status = doc.get("status", "live")
    # .get with a default, not `or`: an empty cite_url means "there is nowhere
    # to link" and must survive. `or` would substitute the dead original URL —
    # which is precisely the 404 this whole change removes.
    cite_url = doc.get("cite_url", doc["url"])
    for heading, body in split_sections(doc["text"]):
        for piece in window(body, settings.chunk_size, settings.chunk_overlap):
            prefix = f"{doc['title']} > {heading}\n" if heading else f"{doc['title']}\n"
            text = prefix + piece
            cid = hashlib.sha1(f"{doc['url']}|{text}".encode()).hexdigest()[:16]
            chunks.append(
                {
                    "id": cid,
                    "text": text,
                    "title": doc["title"],
                    "heading": heading,
                    "url": doc["url"],
                    # url is identity; cite_url is what the user clicks. For an
                    # archived page they differ, and "" means "render this source
                    # without a link" rather than "link to nowhere".
                    "cite_url": cite_url,
                    "status": status,
                    "section": doc.get("section", ""),
                    "date": date,
                }
            )
    return chunks


def build() -> dict[str, Any]:
    docs = load_documents()
    if not docs:
        raise SystemExit(
            f"No documents in {settings.raw_dir}.\n"
            f"Run: python -m scripts.crawl_yzu"
        )

    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        for chunk in chunk_document(doc):
            if chunk["id"] not in seen:
                seen.add(chunk["id"])
                chunks.append(chunk)
    log.info("produced %d unique chunks", len(chunks))

    vectors = None
    if dense_available():
        batch, parts = 32, []
        for i in range(0, len(chunks), batch):
            parts.append(embed([c["text"] for c in chunks[i : i + batch]]))
            log.info("embedded %d/%d", min(i + batch, len(chunks)), len(chunks))
        import numpy as np

        vectors = np.vstack(parts) if parts else None
    else:
        log.warning("no dense backend — index will be lexical-only")

    # The corpus spans two generations of the source site. "pages" carries the
    # link each source is cited by, so a link check has something to verify
    # without re-reading data/raw — the one assertion that keeps the 404
    # regression from coming back unnoticed.
    pages = sorted(
        (
            {
                "url": d["url"],
                "cite_url": d.get("cite_url", d["url"]),
                "status": d.get("status", "live"),
            }
            for d in docs
        ),
        key=lambda d: d["url"],
    )
    by_status: dict[str, int] = {}
    for page in pages:
        by_status[page["status"]] = by_status.get(page["status"], 0) + 1

    manifest = {
        "documents": len(docs),
        "chunks": len(chunks),
        # Every citation resolves on ai.yzu.edu.tw itself: "live" cites its own
        # exact URL, "archived" cites the centre's current home page since that
        # exact page is retired. No third status — nothing is ever unlinkable.
        "live": by_status.get("live", 0),
        "archived": by_status.get("archived", 0),
        "dense": vectors is not None,
        "embedding_model": settings.embedding_model if vectors is not None else None,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "sources": sorted({d["url"] for d in docs}),
        "pages": pages,
    }
    save_index(chunks, vectors, manifest)
    reset_cache()
    log.info(
        "index built: %d docs, %d chunks, dense=%s",
        manifest["documents"],
        manifest["chunks"],
        manifest["dense"],
    )
    return manifest


if __name__ == "__main__":
    argparse.ArgumentParser(description="Build the RAG index").parse_args()
    build()

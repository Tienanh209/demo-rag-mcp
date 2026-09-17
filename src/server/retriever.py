"""Hybrid retrieval: dense + BM25 fused by reciprocal rank fusion, then an
optional cross-encoder rerank.

RRF is used instead of averaging scores because cosine similarity and BM25 live
on different scales — fusing by rank sidesteps normalisation entirely. The final
score reported to the caller is a normalised confidence in [0, 1], because the
client's refusal threshold needs something comparable across queries.
"""

import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from src.common.config import settings
from src.common.trace import get_logger
from src.server.store import dense_available, load_index, tokenize

log = get_logger("server.retriever")
RRF_K = 60


@dataclass
class Hit:
    id: str
    text: str
    title: str
    heading: str
    url: str
    cite_url: str
    status: str
    score: float
    matched_by: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder

    log.info("loading reranker %s", settings.reranker_model)
    return CrossEncoder(settings.reranker_model)


def search(query: str, top_k: int | None = None) -> list[Hit]:
    top_k = top_k or settings.top_k_final
    index = load_index()
    if not index.chunks:
        return []

    dense = index.dense_search(query, settings.top_k_dense)
    lexical = index.lexical_search(query, settings.top_k_lexical)

    fused: dict[int, dict[str, Any]] = {}
    for rank, (idx, sim) in enumerate(dense, start=1):
        fused[idx] = {"rrf": 1 / (RRF_K + rank), "dense": rank, "lexical": None, "sim": sim}
    for rank, (idx, _bm) in enumerate(lexical, start=1):
        if idx in fused:
            fused[idx]["rrf"] += 1 / (RRF_K + rank)
            fused[idx]["lexical"] = rank
        else:
            fused[idx] = {"rrf": 1 / (RRF_K + rank), "dense": None, "lexical": rank, "sim": 0.0}

    if not fused:
        return []

    ranked = sorted(fused.items(), key=lambda kv: kv[1]["rrf"], reverse=True)
    candidates = ranked[: max(top_k * 3, top_k)]

    if settings.enable_reranker and dense_available():
        pairs = [(query, index.chunks[i]["text"]) for i, _ in candidates]
        scores = _reranker().predict(pairs)
        order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)[:top_k]
        selected = [(candidates[i][0], _sigmoid(float(scores[i]))) for i in order]
    else:
        selected = [
            (i, _confidence(query, index.chunks[i]["text"], fused[i]["sim"]))
            for i, _meta in candidates[:top_k]
        ]

    hits: list[Hit] = []
    for idx, confidence in selected:
        chunk = index.chunks[idx]
        meta = fused[idx]
        hits.append(
            Hit(
                id=chunk["id"],
                text=chunk["text"],
                title=chunk["title"],
                heading=chunk["heading"],
                url=chunk["url"],
                cite_url=chunk.get("cite_url", chunk["url"]),
                status=chunk.get("status", "live"),
                score=confidence,
                matched_by=(
                    "both" if meta["dense"] and meta["lexical"]
                    else "dense" if meta["dense"] else "lexical"
                ),
            )
        )
    # RRF chose *which* chunks; confidence decides the order they are shown in.
    # Leaving them in RRF order produced a rank-1 hit scoring below rank-3,
    # which is indefensible in a citation list and breaks the caller's habit of
    # reading passages[0] as the best match.
    hits.sort(key=lambda h: h.score, reverse=True)
    log.info("query=%r -> %d hits (top %.3f)", query, len(hits), hits[0].score if hits else 0.0)
    return hits


_STOP = {"的", "是", "在", "了", "和", "與", "有", "為", "嗎", "呢", "什麼", "哪些", "如何",
         "the", "a", "an", "of", "to", "is", "and", "what", "which", "how"}


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _coverage(query: str, text: str) -> float:
    """Fraction of the query's content tokens that appear in the chunk."""
    q = {t for t in tokenize(query) if t not in _STOP}
    if not q:
        return 0.0
    d = set(tokenize(text))
    return len(q & d) / len(q)


def _confidence(query: str, text: str, cosine: float) -> float:
    """Relevance in [0, 1] — separate from the RRF score used for ordering.

    RRF is a *rank* aggregator: the top result scores 1/(k+1) no matter how bad
    it is. Reusing it as a confidence made the refusal threshold decorative —
    an off-topic query and a perfect match both came back at 1.0. Ordering and
    confidence are different questions, so they get different functions.

    Confidence is the stronger of two interpretable signals: cosine similarity
    when a dense backend is present, and query-term coverage, which answers
    "how much of what the user asked about actually appears in this chunk?"
    """
    return round(max(max(cosine, 0.0), _coverage(query, text)), 4)


def get_document(url: str) -> dict[str, Any] | None:
    index = load_index()
    parts = [c for c in index.chunks if c["url"] == url]
    if not parts:
        return None
    return {
        "url": url,
        "cite_url": parts[0].get("cite_url", url),
        "status": parts[0].get("status", "live"),
        "title": parts[0]["title"],
        "text": "\n\n".join(c["text"] for c in parts),
        "chunks": len(parts),
    }


def mode() -> str:
    """The one place that decides which retrieval mode is actually live.

    Hybrid needs both halves — embeddings in the store *and* an encoder able to
    embed the query. Deriving this from the stored vectors alone let the health
    check report "hybrid" while the dense arm silently returned nothing, which
    is the failure a health check exists to catch.
    """
    if load_index().has_dense and dense_available():
        return "hybrid (dense chroma + bm25, RRF)"
    return "lexical only (bm25)"


def _documents() -> dict[str, dict[str, Any]]:
    """Collapse chunks back into one entry per source page."""
    docs: dict[str, dict[str, Any]] = {}
    for c in load_index().chunks:
        doc = docs.setdefault(
            c["url"],
            {
                "url": c["url"],
                "cite_url": c.get("cite_url", c["url"]),
                "status": c.get("status", "live"),
                "title": c["title"],
                "section": c.get("section", ""),
                "date": c.get("date", ""),
                "chunks": 0,
            },
        )
        doc["chunks"] += 1
        # A page's date is set once at ingest, but take the first non-empty one
        # in case an older index is still on disk.
        if not doc["date"] and c.get("date"):
            doc["date"] = c["date"]
    return docs


def news(since: str = "", limit: int = 5) -> list[dict[str, Any]]:
    """Dated articles, newest first.

    Undated pages are never "recent news", and neither are listing pages: an
    index page inherits the date of the newest item it links to, so it would
    otherwise outrank the article it is pointing at.
    """
    items = [
        d
        for d in _documents().values()
        if d["date"] and not d["section"].endswith("_list") and d["section"] != "home"
    ]
    if since:
        items = [d for d in items if d["date"] >= since]
    items.sort(key=lambda d: d["date"], reverse=True)
    return items[: max(1, min(limit, 25))]


def pages() -> list[dict[str, Any]]:
    """Every indexed page with the link it is cited by.

    Exposed so a link check can verify that no citation points at a dead page —
    the regression that made every source in the old index a 404.
    """
    return [
        {"url": d["url"], "cite_url": d["cite_url"], "status": d["status"]}
        for d in sorted(_documents().values(), key=lambda d: d["url"])
    ]


def status() -> dict[str, Any]:
    index = load_index()
    return {
        **{k: v for k, v in index.manifest.items() if k != "sources"},
        "dense_available": dense_available(),
        "reranker_enabled": settings.enable_reranker,
        "mode": mode(),
    }


def sources() -> list[str]:
    return load_index().manifest.get("sources", [])

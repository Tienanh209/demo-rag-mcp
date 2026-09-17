"""Persistence layer — ChromaDB + BM25.

Dense vectors live in a ChromaDB persistent collection: it gives us persistence,
cosine similarity search and metadata filtering without a service to run, and
the metadata is what the section/news tools query.

The BM25 lexical arm stays in-process (rank_bm25.BM25Okapi) because Chroma has
no native BM25 support. Chinese tokenisation still goes through jieba with
character bigrams as a segmentation-independent backstop.
"""

import json
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from src.common.config import settings
from src.common.trace import get_logger

log = get_logger("server.store")

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """Mixed Chinese/English tokenisation for the lexical index.

    Chinese gets both jieba words *and* character bigrams. Bigrams look
    redundant but they are what makes matching robust: jieba segments
    "學分學程可以抵免" and "各學分學程間可互相抵免" differently, so a word-only index
    misses the overlap that a human reads immediately. Bigrams give a
    segmentation-independent backstop, which is standard practice in Chinese IR.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    if _CJK_RE.search(text):
        tokens += [t for t in jieba.cut_for_search(text) if t.strip() and not t.isspace()]
        tokens += cjk_bigrams(text)
    return tokens


def cjk_bigrams(text: str) -> list[str]:
    runs = _CJK_RUN_RE.findall(text)
    out: list[str] = []
    for run in runs:
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return out


# --------------------------------------------------------------------------
# dense backend
# --------------------------------------------------------------------------
# One question fans out into several parallel search calls, and the server runs
# each in a worker thread, so a cold server can have three threads loading the
# model at once. lru_cache does not serialise that: every thread starts its own
# load, torch fails with "Cannot copy out of meta tensor", and the cached result
# becomes None — silently downgrading the whole process to BM25 only, which also
# invalidates the calibrated refusal threshold. Load it exactly once, under a lock.
_encoder_lock = threading.Lock()
_encoder_loaded = False
_encoder_model: Any = None


def _encoder():
    global _encoder_loaded, _encoder_model
    if _encoder_loaded:
        return _encoder_model
    with _encoder_lock:
        if _encoder_loaded:
            return _encoder_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            log.warning(
                "sentence-transformers not installed — running in lexical-only mode. "
                "Install it for semantic retrieval: pip install sentence-transformers"
            )
        else:
            try:
                log.info("loading embedding model %s", settings.embedding_model)
                _encoder_model = SentenceTransformer(settings.embedding_model)
            except Exception as exc:  # noqa: BLE001 - disk full, bad model name
                log.warning(
                    "could not load %s (%s) — lexical-only mode", settings.embedding_model, exc
                )
        _encoder_loaded = True
        return _encoder_model


def dense_available() -> bool:
    return _encoder() is not None


def embed(texts: list[str], is_query: bool = False) -> np.ndarray | None:
    """Return L2-normalised vectors, or None when no dense backend is available."""
    model = _encoder()
    if model is None:
        return None
    if "e5" in settings.embedding_model.lower():
        prefix = "query: " if is_query else "passage: "
        texts = [prefix + t for t in texts]
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


# --------------------------------------------------------------------------
# ChromaDB client
# --------------------------------------------------------------------------
COLLECTION_NAME = "yzu_chunks"
MANIFEST_PATH = "manifest.json"


# The server runs each tool call in a worker thread, and one question fans out
# into several concurrent search_documents calls. lru_cache does not serialise
# construction — every thread misses the empty cache and builds its own client —
# and Chroma keeps its systems in a process-wide dict that a losing thread tears
# down while the winner is still using it ("no attribute 'bindings'", "could not
# connect to tenant default_tenant"). Build it exactly once, under a lock.
_client_lock = threading.Lock()
_chroma: Any = None
_collection: Any = None


def _get_collection():
    """The chunks collection. No default embedding function — we pass our own
    vectors from sentence-transformers."""
    global _chroma, _collection
    if _collection is None:
        with _client_lock:
            if _collection is None:
                import chromadb

                _chroma = chromadb.PersistentClient(path=str(settings.chroma_dir))
                _collection = _chroma.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
    return _collection


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------
@dataclass
class Index:
    chunks: list[dict[str, Any]]
    has_dense: bool
    manifest: dict[str, Any]

    @property
    def bm25(self) -> BM25Okapi | None:
        if not hasattr(self, "_bm25"):
            self._bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks]) if self.chunks else None
        return self._bm25

    def dense_search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Query ChromaDB for the k nearest neighbours."""
        if not self.chunks:
            return []
        q = embed([query], is_query=True)
        if q is None:
            return []
        collection = _get_collection()
        results = collection.query(
            query_embeddings=q[0].tolist(),
            n_results=min(k, len(self.chunks)),
            include=["distances"],
        )
        # ChromaDB returns cosine *distances* (1 - similarity). Convert to similarity.
        ids = results["ids"][0] if results["ids"] else []
        distances = results["distances"][0] if results["distances"] else []
        id_to_idx = {c["id"]: i for i, c in enumerate(self.chunks)}
        hits = []
        for doc_id, dist in zip(ids, distances):
            idx = id_to_idx.get(doc_id)
            if idx is not None:
                sim = 1.0 - dist  # cosine distance -> cosine similarity
                hits.append((idx, float(sim)))
        return hits

    def lexical_search(self, query: str, k: int) -> list[tuple[int, float]]:
        if self.bm25 is None:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        top = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in top if scores[i] > 0]


def save_index(chunks: list[dict[str, Any]], vectors: np.ndarray | None, manifest: dict) -> None:
    """Upsert chunks and their embeddings into ChromaDB. Also write the manifest."""
    collection = _get_collection()

    # A half-cleared collection leaves the old and new index mixed together, and
    # nothing downstream can detect that. Fail the ingest loudly instead.
    try:
        if collection.count() > 0:
            all_ids = collection.get()["ids"]
            if all_ids:
                collection.delete(ids=all_ids)
    except Exception as exc:
        log.error("could not clear collection %s: %s", COLLECTION_NAME, exc)
        raise

    if chunks:
        ids = [c["id"] for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "title": c.get("title", ""),
                "heading": c.get("heading", ""),
                "url": c.get("url", ""),
                "cite_url": c.get("cite_url", ""),
                "status": c.get("status", "live"),
                "section": c.get("section", ""),
                "date": c.get("date", ""),
            }
            for c in chunks
        ]

        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            end = min(i + batch_size, len(chunks))
            batch_kwargs: dict[str, Any] = {
                "ids": ids[i:end],
                "documents": documents[i:end],
                "metadatas": metadatas[i:end],
            }
            if vectors is not None:
                batch_kwargs["embeddings"] = vectors[i:end].tolist()
            collection.upsert(**batch_kwargs)

    # Also persist chunks.json for the BM25 arm (it needs the full text at load time)
    chunks_path = settings.index_dir / "chunks.json"
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")

    # Manifest
    (settings.index_dir / MANIFEST_PATH).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info("saved %d chunks to ChromaDB + BM25 index", len(chunks))


@lru_cache(maxsize=1)
def load_index() -> Index:
    chunks_file = settings.index_dir / "chunks.json"
    if not chunks_file.exists():
        log.warning("no index at %s — run: python -m src.server.ingest", settings.index_dir)
        return Index(chunks=[], has_dense=False, manifest={"documents": 0, "chunks": 0, "sources": []})
    chunks = json.loads(chunks_file.read_text(encoding="utf-8"))

    # Whether Chroma actually holds embeddings. Separate from dense_available(),
    # which asks whether the encoder can run — hybrid retrieval needs both.
    has_dense = False
    try:
        has_dense = _get_collection().count() > 0
    except Exception as exc:  # noqa: BLE001 - read path, degrade instead of dying
        log.warning("chroma count failed (%s) — treating the index as lexical-only", exc)

    manifest_file = settings.index_dir / MANIFEST_PATH
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    log.info("index loaded: %d chunks, embeddings=%s", len(chunks), "yes" if has_dense else "no")
    return Index(chunks=chunks, has_dense=has_dense, manifest=manifest)


def reset_cache() -> None:
    load_index.cache_clear()

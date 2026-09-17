"""Retrieval evaluation. This produces the numbers for the results slide.

Two metrics, deliberately:

  hit@k / MRR on the *source page* — did we retrieve from the right document?
  answer-span rate — did the retrieved text actually contain the fact?

The second matters more. A system can score a perfect hit@5 while returning the
page's navigation menu, and the answer would still be unusable. Checking for the
expected span is the cheapest available proxy for faithfulness.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from src.common.config import settings
from src.server import retriever

EVAL_PATH = Path(__file__).resolve().parents[1] / "tests" / "eval_set.json"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return round(ordered[idx], 1)


def run(k: int = 5, verbose: bool = False) -> dict:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    doc_rr: list[float] = []
    span_hits = 0
    latencies: list[float] = []
    failures: list[dict] = []

    for case in cases:
        t0 = time.perf_counter()
        results = retriever.search(case["question"], top_k=k)
        latencies.append((time.perf_counter() - t0) * 1000)

        rank = next(
            (i for i, h in enumerate(results, start=1) if case["expect_url_contains"] in h.url),
            None,
        )
        doc_rr.append(1 / rank if rank else 0.0)

        span = case.get("expect_text_contains")
        span_found = bool(span) and any(span in h.text for h in results)
        if span_found:
            span_hits += 1

        if verbose or not span_found:
            failures.append(
                {"question": case["question"], "doc_rank": rank, "span_found": span_found}
            )

    n = len(cases)
    report = {
        "cases": n,
        f"doc_hit@{k}": round(sum(1 for r in doc_rr if r) / n, 3),
        "doc_mrr": round(statistics.mean(doc_rr), 3),
        f"answer_span@{k}": round(span_hits / n, 3),
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
        "retrieval_mode": retriever.status()["mode"],
        "reranker": settings.enable_reranker,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Evaluate retrieval quality")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    run(args.k, args.verbose)

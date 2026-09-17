"""Calibrate MIN_SCORE against real data.

MIN_SCORE decides when the system refuses to answer. Shipping a guessed value is
the single easiest thing for a reviewer to poke a hole in. This script gives you
a defensible number.

Method: score a set of questions the corpus *should* answer, and a set it should
not. A good threshold sits between the two distributions.

    python -m scripts.calibrate
"""

import statistics

from src.server import retriever

# Both halves of the corpus have to be sampled. The live pages are short (the
# apply page is under 200 characters), and _confidence normalises term coverage
# by query length against the chunk text, so a corpus of short pages sits
# differently in the distribution than the long archived ones. Calibrating on
# the archived half alone would leave the live half untested by the threshold
# that decides whether it is ever answered from.
IN_SCOPE = [
    # current site
    "算力申請需要什麼條件",
    "算力平台有幾張 GPU",
    "H200 的記憶體容量",
    "HPC 高速運算平台",
    "中心的聯絡信箱",
    "服務團隊有哪些人",
    # archived site
    "TAICA 有哪些學分學程？",
    "人工智慧視覺技術學分學程的內容",
    "自然語言技術學分學程",
    "人工智慧工業應用學分學程",
    "AI 中心的聯絡電話",
    "中心有哪些設備資源",
    "研究實驗室清單",
    "教學實驗室有哪些",
    "課程資訊在哪裡查詢",
    "AI 中心成立的背景與目的",
    "研究成果有哪些",
    "精密儀器中心",
]

OUT_OF_SCOPE = [
    "今天新竹的天氣如何",
    "how do I cook pasta carbonara",
    "台北捷運的票價",
    "誰贏了昨天的棒球比賽",
    "Python 的 decorator 怎麼寫",
    "推薦一部電影",
]


def top_scores(questions: list[str]) -> list[tuple[str, float, str]]:
    rows = []
    for q in questions:
        hits = retriever.search(q, top_k=1)
        if hits:
            rows.append((q, hits[0].score, hits[0].title))
        else:
            rows.append((q, 0.0, "(no hit)"))
    return rows


def report(label: str, rows: list[tuple[str, float, str]]) -> list[float]:
    print(f"\n{label}")
    print("-" * 72)
    for q, score, title in sorted(rows, key=lambda r: r[1]):
        print(f"  {score:<8.4f} {q[:34]:<36} {title[:26]}")
    scores = [s for _, s, _ in rows]
    print(f"  min {min(scores):.4f}   median {statistics.median(scores):.4f}   max {max(scores):.4f}")
    return scores


def main() -> None:
    good = report("IN SCOPE — these must be answered", top_scores(IN_SCOPE))
    bad = report("OUT OF SCOPE — these must be refused", top_scores(OUT_OF_SCOPE))

    print("\n" + "=" * 72)
    lowest_good, highest_bad = min(good), max(bad)
    print(f"lowest in-scope score  : {lowest_good:.4f}")
    print(f"highest out-of-scope   : {highest_bad:.4f}")

    if lowest_good > highest_bad:
        suggested = round((lowest_good + highest_bad) / 2, 3)
        print(f"\nClean separation. Set MIN_SCORE={suggested} in .env")
        print(f"Margin: {lowest_good - highest_bad:.4f}")
    else:
        overlap_good = [s for s in good if s <= highest_bad]
        overlap_bad = [s for s in bad if s >= lowest_good]
        print("\nThe distributions overlap — no threshold separates them perfectly.")
        print(f"  {len(overlap_good)} in-scope question(s) score below the worst out-of-scope one")
        print(f"  {len(overlap_bad)} out-of-scope question(s) score above the worst in-scope one")
        print("\nPick based on which error you prefer:")
        print(f"  MIN_SCORE={round(highest_bad + 0.01, 3)}  -> never hallucinates, refuses some real questions")
        print(f"  MIN_SCORE={round(lowest_good - 0.01, 3)}  -> answers everything real, occasionally guesses")
        print("\nThis trade-off is worth one slide. Say which side you chose and why.")
    print("=" * 72)


if __name__ == "__main__":
    main()

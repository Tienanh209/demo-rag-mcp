# YZU AI Center — MCP client/server RAG

A Model Context Protocol client–server system that answers questions about the
Yuan Ze University AI Center (元智大學人工智慧跨域創新應用中心, ICAIA) from its own
website, with citations back to the source page.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
make install          # or: pip install -e ".[dev]"
make ingest           # builds the index from the seed corpus in data/raw
make demo             # scripted conversation over MCP stdio
make run              # web console at http://127.0.0.1:8000
```

**A language model is required.** Set `LLM_API_KEY` in `.env` (any
OpenAI-compatible endpoint). The client checks for one at startup and exits with
an actionable message rather than starting up and then refusing every question.

That requirement is deliberate. The corpus is Traditional Chinese, and an
English question only retrieves well once it has been rewritten into Chinese
search terms — which is a model's job. An earlier build answered without a model
by copying sentences out of the passages; for an English question over a Chinese
corpus that produced unreadable output, so it was removed in favour of failing
clearly.

Within a running turn the system still degrades rather than breaking: a failed
rewrite falls back to a deterministic path (including English→Chinese terms), a
failed generation returns the sources with a plain explanation, and the trace
records which path actually ran.

---

## Why this shape

**The server knows nothing about conversations.** It exposes retrieval and
nothing else — no memory, no LLM, no chat state. That boundary is the point of
MCP: the same server process serves this client, Claude Desktop, or any other
host without a line of change. Everything conversational lives in the client.

**Three MCP primitives, not one.** Most implementations expose Tools only. This
one also exposes Resources (`yzu://doc/{url}`, so a host can read a source page
directly) and a Prompt (`grounded_answer`, a citation-first template the server
ships alongside its data).

**Transport is a deployment decision, not an architecture one.** `stdio` (the
default) has the client spawn the server as a subprocess — the same mechanism
Claude Desktop uses. `MCP_TRANSPORT=http` runs the server standalone for a split
deployment. One environment variable, no code change.

---

## Architecture

```
user
 └─ MCP client  (src/client)              conversation, memory, orchestration
     ├─ intent.py       rule fast-path, LLM only for ambiguous messages
     │                  knowledge | follow_up | chitchat | meta | out_of_scope
     ├─ router.py       intent -> subagent pipeline (a table, not if/else)
     ├─ memory.py       short-term buffer / working entities / rolling summary
     └─ agents/
         ├─ planner.py              intent + tool + queries in one small-model call
         ├─ retrieval_agent.py      query rewriting + multi-query -> MCP tools
         ├─ answer_agent.py         grounded generation, refusal below threshold
         └─ summary_agent.py        long-term memory compaction
            │
            │  MCP  (JSON-RPC over stdio, or streamable HTTP)
            ▼
    MCP server  (src/server)              retrieval only
     ├─ app.py        tools:     search_documents, get_document, get_news,
     │                           index_status
     │                resources: yzu://doc/{url}, yzu://index/manifest
     │                prompts:   grounded_answer
     ├─ retriever.py  dense + BM25 ordered by RRF; confidence scored separately
     ├─ ingest.py     heading-aware chunking, 500 chars, 80 overlap
     └─ store.py      ChromaDB persistent collection + rank_bm25 + jieba
```

### Design decisions worth defending

| Decision | Why |
|---|---|
| Hybrid dense + BM25 | Dense alone misses exact identifiers (程式代號, 學程 names). BM25 alone misses paraphrase. |
| RRF for ordering | Cosine and BM25 live on different scales; fusing by rank avoids normalising them. |
| Confidence computed separately from RRF | RRF's top result always scores 1/(k+1) regardless of quality. Reusing it as confidence made the refusal gate decorative — see "Bugs the build found". |
| jieba **and** character bigrams | jieba segments query and document differently ("學分學程可以抵免" vs "各學分學程間可互相抵免"). Bigrams are a segmentation-independent backstop. |
| Heading prefix inside each chunk | A fragment keeps its context: "TAICA聯盟學分學程介紹 > 人工智慧視覺技術學分學程" instead of an orphaned sentence. |
| Refusal in control flow, not in the prompt | A model handed weak context still writes a confident paragraph. `MIN_SCORE` decides before generation. |
| Query rewriting before search | "那個學程呢？" retrieves nothing standalone; resolved against memory it retrieves correctly. |
| Three memory tiers | Different lifetimes, different token costs. One blob either forgets too fast or floods the context. |
| ChromaDB for the dense arm | Persistence, cosine search and metadata filtering without a service to run — and the metadata is what `get_news` filters on, and what carries each chunk's `status` and `cite_url`. At this corpus size a flat matmul would also work; Chroma is chosen for the metadata query surface, not for ANN speed. |
| The client picks the tool, the server just offers them | `search_documents` cannot answer "what's new" — that needs date ordering, not relevance. So the server exposes `get_news` too, and the client chooses between them from the schemas MCP already sends at discovery. Hardcoding one call site would have thrown that away. |
| One planner call, not three | Intent, tool choice and query rewriting are the same kind of decision — read the message, decide how to look things up — and they were three sequential requests to the generation model before a single passage had been fetched. They are now one request to a smaller model (`ROUTER_MODEL`). The trace still reports them as three stages, because they are three decisions; they just no longer cost three round trips. |
| The corpus spans two generations of the site | The source site was rebuilt in 2026 and every previous URL now returns 404. Re-crawling alone would have shrunk the corpus to a handful of pages, and the crawler's own BFS missed a whole live category (TAICA, catid=9) that nothing on the site links to. The retired documents that have no live equivalent stay in the index, labelled `archived`, but every citation — theirs included — resolves on ai.yzu.edu.tw itself. No third-party archive is ever in the loop: `scripts/resolve_sources.py` retires a retired document outright when the BFS crawl found the same content live, and otherwise cites the centre's own current home page. |

---

## Measured results

Full corpus (51 pages — 13 live, 38 archived — 407 chunks), hybrid mode, `make eval`:

```
doc_hit@5        1.000
doc_mrr          0.912
answer_span@5    0.947
latency_p50      61.5 ms
```

Nine documents that the archive originally carried were retired outright once
`scripts/resolve_sources.py` found their content on the live site (TAICA's five
credit programs, its overview, and two news articles), so `eval_set.json` was
re-pointed at wherever each fact actually lives now — confirmed against real
`retriever.search()` output, not guessed. That is also why the corpus shrank
from 60 pages to 51: the live copy is strictly better than the retired
duplicate it replaced, and letting both stand only made them compete for rank.

Citations, `make check-links`:

```
live     13  all 200, on ai.yzu.edu.tw
archived 38  all 200, on ai.yzu.edu.tw (never a third-party archive)
404s      0
```

`answer_span` is the metric that matters: it checks the retrieved text actually
contains the expected fact. A system can score a perfect `hit@5` while returning
a page's navigation menu — which is why it is reported separately, and why it is
the lowest number here rather than the flattering one.

### What the crawler fix did to the corpus

The extraction bugs below were not cosmetic. Fixing them removed 43% of the
index as pure noise:

| | before | after |
|---|---|---|
| corpus characters | 206,488 | 117,932 |
| chunks | 923 | 373 |
| duplicated lines | 207 across 9 pages | 4 on 1 page (the source page really does repeat itself) |
| largest page's share | 61% | 46% |
| table rows preserved | 0 | 168 |

### The 2026 site rebuild, and the category nothing links to

The source site was rebuilt on Joomla in 2026. Every pre-rebuild URL now
404s — confirmed by testing all 47 URLs in the old index — so every citation
the assistant had ever produced pointed at a dead page. `scripts/crawl_yzu.py`
was rewritten for the new `/index.php/tw/...` scheme.

The first fix cited the retired pages through the Wayback Machine. That is the
wrong fix: a citation on this project is "click here to see this on the
centre's own site", and web.archive.org is not that, however well it resolves.
The real fix needed no third party — it needed the corpus to be re-investigated
properly (see below), because most of what looked retired was not:

The first re-crawl of the new site found only 6 pages: home, `apply`, `intro`,
and 3 news articles. Nothing on the site linked to the TAICA credit-program
content at all — no nav item, no home-page teaser, no breadcrumb. It was found
by sweeping Joomla category IDs (`/component/content/category/<id>` for
0–40) against the live site and checking which returned real content: `catid=9`
is "臺灣大專院校人工智慧學程聯盟(TAICA)", with all 5 credit programs still
published, just orphaned from navigation. `CONTENT_CATEGORIES = (9, 10)` in
the crawler now seeds it explicitly, with a comment explaining why — losing
that seed makes the crawl "succeed" while silently omitting the site's actual
subject matter, which is a failure mode worth naming rather than leaving to be
rediscovered.

One more Joomla quirk worth recording: `?Itemid=101` on every content URL is
the active-menu highlight, not part of the address — `/apply`, `/apply?Itemid=
101` and `/apply?Itemid=999` return byte-identical content. `catid`, on the
other hand, is real: an article and its category listing share the exact same
`/component/content/article|category/...` URL shape, and `catid` is the only
thing left in it that tells a TAICA program apart from a news item once
`Itemid` is dropped. The crawler keeps `catid`, drops `Itemid`, and classifies
`section` from whichever of the two carries it (query string for an article,
path segment for a category listing).

**`scripts/resolve_sources.py` replaced the Wayback resolver entirely** — no
network calls, no rate limits, nothing to cache, deterministic:

1. Any retired document whose title matches a live document's title is
   retired outright: 9 of the original 47 were exact duplicates of content the
   TAICA-category recovery above had already brought back live (the 5 credit
   programs, the TAICA overview, 2 news articles). Keeping both meant the live
   and retired copies competed for rank in retrieval, so the retired copy is
   simply deleted from `data/raw` — the live one is strictly better: current,
   real, and no longer splitting relevance between two entries.
2. Everything else (teacher pages, equipment, old news, lab notices — 38
   documents) genuinely has no live page any more. Its citation is the centre's
   own current home page, `https://ai.yzu.edu.tw/index.php/tw` — not a page
   that merely mentions the topic (a citation that looks specific but points
   at the wrong thing is worse than no citation), and never a URL outside the
   real domain.

Corpus today: 51 pages — 13 live, 38 archived, every citation on ai.yzu.edu.tw
— 407 chunks, `make check-links` reports 0 broken links and 0 external domains.

### Calibrating the refusal threshold

```bash
make calibrate
```

Scores questions the corpus *should* answer against ones it should not, and
reports where the distributions separate. On the full corpus:

```
lowest in-scope      0.8619
highest out-of-scope 0.8489
suggested MIN_SCORE  0.855   (margin 0.013)
```

Those numbers are measured **through the query-rewrite step the client actually
runs**, over 19 in-scope questions (12 Chinese, 7 English) and 8 off-topic ones.
Scoring the raw question instead — which is what `make calibrate` does today —
describes a pipeline the product does not run: raw English questions all land in
0.77–0.84 whether they are relevant or not, and no threshold separates them.

Two things worth saying plainly about that number.

**It was not being enforced.** `MIN_SCORE` sat at `0.35` while every query —
including "推薦一部電影" — scored above `0.83`. The refusal gate was live code
that could never fire. Calibration is what surfaced it; nothing in the test
suite would have.

**The margin is thin because of the embedding model, not the corpus.**
`multilingual-e5-small` has a high similarity floor: unrelated text pairs sit
around 0.75–0.85, so the usable band is narrow and a single badly-worded
out-of-scope question could still cross it. Widening it properly means scoring
the top hit against the corpus's own background similarity instead of using raw
cosine — the honest next step, and not yet done.

---

## Bugs the build found

Kept here because they are the interesting part of the work.

1. **RRF is a rank aggregator, not a relevance score.** The top result always
   scores 1/(k+1). `calibrate.py` showed "今天新竹的天氣如何" and
   "TAICA 有哪些學分學程" both returning 1.0000 — the refusal gate could not
   separate them. Fixed by scoring confidence as `max(cosine, query coverage)`,
   leaving RRF to do ordering only.
2. **jieba segments queries and documents inconsistently**, so a word-only index
   missed overlaps a human reads instantly. Fixed with CJK character bigrams.
3. **`lru_cache` does not serialise construction.** It bit twice. One question
   fans out into parallel `search_documents` calls, each running in its own
   worker thread, so a cold server has three threads building the same
   singleton at once. For the ChromaDB client that corrupted a process-wide
   registry; for the embedding model, torch failed with "Cannot copy out of meta
   tensor" and the cached result became `None` — silently downgrading every
   later query in that process to BM25 only, which also invalidates the
   calibrated threshold. Both are now built once under a lock. Reproducible with
   three threads and a barrier; the encoder failed 2 runs out of 3 before the fix
   and 0 out of 5 after.
4. **The site's name was inside all 923 chunks.** The crawler stripped the site
   name as a *suffix*; this site puts it as a *prefix*. So every title kept
   it, and since ingest prepends the title to every chunk, every chunk opened
   with the same 12 characters. Cosmetic-looking, but it pushes every embedding
   toward one point and costs the refusal gate the margin it needs.
5. **`find_all()` is recursive, so nested tags were emitted twice.** A `<li>`
   wrapping a `<p>` produced its text once for each — 207 duplicated lines. The
   fix tracks emitted nodes by identity rather than by text, so a page that
   genuinely repeats a short string still keeps both copies.
6. **One professor's publication list was 57% of the corpus.** It is rendered
   under two tabs, so it was indexed twice, and it won every search — including
   "quantum blockchain marketing strategy". The two copies are not byte-equal
   (each carries its own tab label), so exact-match dedup missed them; matching
   on an interior window of the normalised text catches them.
7. **Concurrent tool calls corrupted the Chroma client.** One question fans out
   into several `search_documents` calls, the server runs each in a worker
   thread, and `@lru_cache` does not serialise construction — so every thread
   built its own client, and Chroma's process-wide system registry let a losing
   thread tear down the winner's (`'RustBindingsAPI' object has no attribute
   'bindings'`). Intermittent, and invisible until the first call on a cold
   server. Fixed with double-checked locking; reproducible with four threads and
   a barrier.

---

## Commands

```bash
make help          # list targets
make crawl         # refresh data/raw from ai.yzu.edu.tw (needs network)
make ingest        # rebuild the index
make demo          # scripted end-to-end conversation
make smoke         # server-side health check, no LLM involved
make calibrate     # find a defensible MIN_SCORE
make eval          # retrieval metrics
make test          # unit tests
make run           # web console
make cli           # terminal client
make stdio-config  # print the Claude Desktop config block
```

---

## Connecting to Claude Desktop

Proves the server is a real MCP server rather than an HTTP API wearing the name.

```bash
make stdio-config
```

Paste the output into `claude_desktop_config.json`, restart, and the four tools
appear in the host.

---

## Demo script

1. **Direct question** — `TAICA 有哪些學分學程？` Answer arrives with `[1][2]`
   citations; open a link and check it against the live site.
2. **Follow-up** — `那個視覺技術的適合哪些學生？` No antecedent in the sentence.
   The trace panel shows the rewritten query. This is memory doing work.
3. **A question search cannot answer** — `最近有什麼新消息？` Keyword relevance
   cannot order by date, so the client picks `get_news` instead. Open the trace
   and show the `tool` stage: the tools it was offered, the one it chose, and
   why — decided inside the planner call, so it costs no extra request. Same
   question shape, a different tool — that is the MCP part of the system doing
   real work.
4. **Out of scope** — `今天新竹的天氣如何？` The system refuses and says why. The
   refusal is the feature — and worth saying out loud that it was silently
   disabled until calibration caught it.
5. **Trace panel** — walk intent → router → tool → MCP call → answer for
   one turn, and expand a payload.
6. **Sidebar** — reload the page: the conversation is still there. Switch to an
   older one and it comes back from `data/memory/`.
7. **Claude Desktop** — same server, different host, no code change.

---

## Repository layout

```
src/server/      MCP server: tools, resources, prompts, retrieval
src/client/      MCP client: intent, router, memory, subagents, web + CLI
scripts/         crawl_yzu, ingest helpers, demo, smoke, calibrate, evaluate
web/             demo console — index.html + app.css + app.js, no build step
tests/           unit tests and the evaluation set
data/raw/        corpus: the current site plus retired content kept from
                 before the rebuild. `make crawl` adds live pages; it never
                 deletes archived ones, because every one of them exists
                 nowhere else — not on the site, and (deliberately) not
                 depended on anywhere on the web either. `scripts/
                 resolve_sources.py` points each at a real ai.yzu.edu.tw URL.
data/memory/     one JSON file per conversation, listed by the sidebar
```

---

## Known limitations

- **The refusal margin is 0.023.** It separates the calibration set cleanly, but
  it is narrow enough that an unusual out-of-scope question could cross it. See
  "Calibrating the refusal threshold" for why, and for the fix that is not done.
- **English questions depend on the rewrite step.** The corpus is Chinese, so an
  English question only scores well once it has been rewritten into Chinese
  terms. If that one call fails, a built-in English→Chinese map covers about
  twenty demo topics; an English question outside them would be refused.
- **One page is 46% of the corpus** (a research professor's publication list).
  Real content, but it skews term statistics and still surfaces on loosely
  related English queries.
- Index is a point-in-time snapshot. No incremental update or change detection.
- Single-process, in-memory index. Fine to a few thousand chunks.
- No authentication on the web client — this is a lab deployment.
- Evaluation covers retrieval and answer-span. Faithfulness of *generated*
  answers is still judged by hand; a RAGAS pass is the next step.
- `scripts/calibrate.py` scores raw questions, not rewritten ones, so its output
  understates English performance. The numbers above were measured through the
  rewrite path by hand; folding that into the script is the next clean-up.
- `scripts/smoke_server.py` and `scripts/calibrate.py` were reviewed line by
  line but not authored in the main pass — read them before relying on them.

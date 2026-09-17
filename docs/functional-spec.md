# Functional Specification — YZU AI Center Assistant

| | |
|---|---|
| Version | 1.0 |
| Date | 2026-09-10 |
| Author | Anh Cao |
| Status | Implemented. Open issues are listed in §11. |
| Companion | `docs/YZU-AI-Center-Assistant.pptx` (presentation), `README.md` (setup, design notes) |

---

## 1. Purpose and scope

The system answers questions about the Yuan Ze University AI Center
(元智大學人工智慧教學與應用發展中心; formerly 人工智慧跨域創新應用中心, ICAIA) from the
center's own website — the current site plus an archived snapshot of the site it
replaced,
`ai.yzu.edu.tw`, and cites the page each claim comes from.

It is a Model Context Protocol (MCP) client–server application:

- the **MCP server** provides retrieval-augmented-generation (RAG) retrieval over
  an index of the website, and nothing else — no conversation state, no LLM;
- the **MCP client** manages the conversation (intent, routing, memory,
  subagents) and answers by calling the server's tools.

**In scope:** TAICA credit programs, courses, faculty, labs, equipment, news
and notices published as HTML pages on `ai.yzu.edu.tw`.

**Out of scope:** everything else (weather, general programming help, other
universities), and the contents of PDF or Word files linked from the site,
which are not crawled.

---

## 2. Users and use cases

| Actor | Description |
|---|---|
| Visitor | A student, prospective student or staff member. Asks questions in the web console or CLI, in English or Traditional Chinese. |
| Operator | Rebuilds the index, calibrates the refusal threshold, runs the demo. |
| External MCP host | Another MCP client, such as Claude Desktop, using the server directly with its own model and conversation. |

| ID | Use case | Requirement |
|---|---|---|
| UC-1 | Ask a factual question about the center | FR-01 |
| UC-2 | Ask a follow-up that depends on the previous answer | FR-02 |
| UC-3 | Ask what is new | FR-03, FR-04 |
| UC-4 | Ask what exists of a kind (faculty, downloads) | FR-03, FR-05 |
| UC-5 | Ask something the center's website cannot answer | FR-07 |
| UC-6 | Resume or delete an earlier conversation | FR-10 |
| UC-7 | Inspect how an answer was produced | FR-11 |
| UC-8 | Refresh the knowledge base | FR-14 |
| UC-9 | Use the server from another MCP host | FR-15 |

---

## 3. System context

```
 Visitor ──► Web console (web/)  ─┐
         ──► Terminal CLI         ├─► MCP client (src/client)
                                  │     intent → router → subagents → memory
                                  │            │
                                  │            │  MCP: JSON-RPC over stdio (default)
                                  │            │       or streamable HTTP
                                  │            ▼
 Claude Desktop ──────────────────┴──► MCP server (src/server)
                                        tools · resources · prompt
                                        hybrid retrieval: ChromaDB + BM25
                                              ▲
                     crawl_yzu.py → ingest.py ┘   (offline data pipeline)

 LLM endpoint (OpenAI-compatible, optional) ◄── client only
```

The client starts the server as a subprocess over stdio, the same mechanism
Claude Desktop uses. Setting `MCP_TRANSPORT=http` runs the server standalone
for a split deployment; no code changes.

---

## 4. Functional requirements

| ID | Requirement | Acceptance criteria | Implemented in |
|---|---|---|---|
| FR-01 | **Grounded answer.** For an in-scope question, return an answer in which every factual sentence carries a citation `[n]`, and return the matching citations `{n, title, heading, url, score}`. | Citations are non-empty and every URL is an indexed page. The answer states nothing the cited passages do not support (checked by hand). | `agents/answer_agent.py`, `agents/retrieval_agent.py` |
| FR-02 | **Follow-up resolution.** A message that depends on earlier turns ("那個學程呢？") is classified `follow_up` and rewritten into standalone search queries using working memory before retrieval. | In the demo, the trace shows the rewritten query and the answer is grounded. | `intent.py`, `retrieval_agent.py`, `memory.py` |
| FR-03 | **Tool selection.** For retrieval intents, choose one tool from those the server advertised at discovery, using their descriptions and argument schemas. Decided in the same call as FR-01 and FR-04. Reject tool names the server did not advertise, drop undeclared arguments, and use `search_documents` when the choice is missing or invalid. | "最近有什麼新消息？" and "What's the latest news from the centre?" both select `get_news`; a hallucinated tool name falls back to `search_documents` and is recorded in the trace. | `planner.py`, `mcp_session.py` |
| FR-04 | **Date-ordered news.** List dated articles newest first, optionally from a given date. Undated pages and listing pages are excluded. | Items are in descending date order; none is a `*_list` page. | server `get_news`, `retriever.news` |
| FR-05 | **Source provenance.** Every indexed page carries a status — `live` or `archived` — and the URL it is cited by. A live page cites its own exact URL; an archived page (one whose exact page no longer exists) cites the centre's current home page instead. Every citation resolves on ai.yzu.edu.tw itself — never a third-party archive, never a dead page. | A TAICA answer cites its live program page directly; an equipment question with no live page cites the home page, shown on a dashed chip. `make check-links` reports zero 404s and zero non-ai.yzu.edu.tw domains. | `scripts/resolve_sources.py`, `retriever.pages`, `web/app.js` |
| FR-06 | **Deep read.** If the best passage is shorter than 300 characters and scores above the threshold, fetch the whole page once with `get_document` and use its first 1,500 characters. | At most one `mcp:get_document` step per turn, recorded in the trace. | `retrieval_agent._deep_read` |
| FR-07 | **Refusal.** If the best passage's confidence is below `MIN_SCORE`, reply with a fixed refusal that states the index's scope, and make no generation call. Messages with off-topic vocabulary and no in-scope vocabulary are refused at intent classification, before any retrieval. | All 6 off-topic calibration questions are refused; all 12 answerable ones are answered. | `answer_agent.py`, `intent.py`, `router.py` |
| FR-08 | **Chit-chat and meta questions.** Greetings and questions about the assistant receive a fixed reply in the interface language, without retrieval. | "你好" and "你的資料來源是什麼？" produce no MCP call. | `router.get_canned` |
| FR-09 | **Language.** Interface and answers in English or Traditional Chinese, selected in the interface and sent with every message. | Switching language changes labels, the greeting and the language of new answers. | `web/app.js`, `answer_agent.py` |
| FR-10 | **Sessions.** Each conversation persists on the server as `data/memory/{session_id}.json`, titled by its first question and keeping up to 200 turns. The sidebar lists sessions newest first, grouped Today / Yesterday / Previous 7 days / Older. Selecting one restores its transcript; deleting one requires confirmation in a dialog. The browser remembers the active session across reloads. | Reloading the page restores the conversation; deletion removes the file. | `memory.py`, `web.py`, `web/app.js` |
| FR-11 | **Reasoning trace.** Every response includes the trace steps `{stage, detail, ms, payload}` and the list of subagents run. The interface shows them per turn, with expandable payloads. Stage prefixes: `intent`, `router`, `tool`, `subagent:*`, `mcp:*`. | The trace for a news question shows a `tool` stage with the chosen tool, the catalog it chose from, and a note that it was decided inside the planner call. | `common/trace.py`, `orchestrator.py`, `web/app.js` |
| FR-12 | **Status reporting.** Show the transport, tool count, chunk count and live retrieval mode. The mode is `hybrid` only when embeddings are stored **and** the encoder can run; otherwise `lexical`. | Removing the embedding model changes the badge to `lexical`. | `retriever.mode`, `/api/status`, `web/app.js` |
| FR-13 | **Fail fast, then degrade within a turn.** A language model is required: the client checks for one at startup and exits with an actionable message rather than starting up and refusing every question. Once running, a single failed call degrades rather than failing the turn — query rewriting falls back to a deterministic path (including English→Chinese search terms), the trace records `rule-fallback` instead of `llm`, a failed generation returns its sources with a plain explanation, and a failed summary never loses the answered turn. Without an embedding model, retrieval is BM25-only and the status badge says so. | Starting with an empty `LLM_API_KEY` exits immediately. With the endpoint unreachable, "Which teachers are at the centre?" still retrieves grounded Chinese passages (0.88 > `MIN_SCORE`). | `llm.py`, `answer_agent.py`, `retrieval_agent.py`, `summary_agent.py`, `store.py` |
| FR-14 | **Knowledge-base refresh.** The operator can crawl, ingest, calibrate and evaluate with one command each. | `make crawl`, `make ingest`, `make calibrate`, `make eval` complete. | `scripts/`, `src/server/ingest.py` |
| FR-15 | **External MCP host.** The server runs standalone over stdio (or HTTP) and can be registered in Claude Desktop with the configuration printed by `make stdio-config`, without code changes. | Claude Desktop lists the four tools and answers through them. | `src/server/app.py`, `Makefile` |

---

## 5. MCP server interface

The server holds no conversation state and makes no LLM calls. Every tool
returns a JSON string.

### 5.1 Tools

| Tool | Arguments | Returns |
|---|---|---|
| `search_documents` | `query: str`, `top_k: int = 5` (clamped to 1–10) | `{query, count, results: [{rank, score, title, heading, url, text, matched_by}]}` |
| `get_document` | `url: str` | `{url, title, text, chunks}`, or `{error: "not_indexed", url}` |
| `get_news` | `since: str = ""` (ISO date), `limit: int = 5` (1–25) | `{since, count, items: [{url, title, section, date, chunks}]}` |
| `index_status` | — | manifest fields plus `{dense_available, reranker_enabled, mode}` |

### 5.2 Resources and prompt

| Kind | Name | Content |
|---|---|---|
| Resource | `yzu://doc/{url_id}` | Full text of one indexed page (`url_id` is the URL-encoded URL) |
| Resource | `yzu://index/manifest` | Index status and the list of sources |
| Prompt | `grounded_answer(question, language="zh-TW")` | Citation-first answering template a host can reuse |

### 5.3 Transport

`stdio` by default (the client spawns the server). With `MCP_TRANSPORT=http`
the server listens on `MCP_HOST:MCP_PORT` (default `127.0.0.1:8100`) using
streamable HTTP at `/mcp`.

---

## 6. Client HTTP interface

Served by FastAPI on `CLIENT_HOST:CLIENT_PORT` (default `127.0.0.1:8000`).

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/chat` | `{message: 1–2000 chars, session_id: ^[A-Za-z0-9_-]{1,64}$ (default "demo"), lang: "en" \| "zh"}` | `{answer, intent, grounded, citations[], trace[], agents[]}`. 422 on invalid input; 500 with `detail` if the turn fails. |
| GET | `/api/status` | — | `{transport, tools[], index{...}}` |
| GET | `/api/sessions` | — | `{sessions: [{session_id, title, updated_at, turns}]}`, newest first |
| POST | `/api/sessions` | — | `{session_id: "s-xxxxxxxx"}`. Nothing is written until the first turn. |
| GET | `/api/sessions/{id}` | — | `{session_id, title, summary, turns: [{role, content}]}`. 400 on an invalid id. |
| DELETE | `/api/sessions/{id}` | — | `{ok: bool}`. 400 on an invalid id. |
| GET | `/healthz` | — | `{ok}` |
| GET | `/` | — | The web console, sent with `Cache-Control: no-cache` |

Static assets are served under `/static`.

---

## 7. Conversation pipeline

### 7.1 Intent classification

Rules are tried in this order; the first match wins. Only if none matches is
the LLM asked (or, with no LLM, the message is treated as `knowledge` at 0.5).

| Order | Rule | Intent | Confidence |
|---|---|---|---|
| 1 | The whole message is a greeting or thanks | `chitchat` | 0.99 |
| 2 | Asks about the assistant, its sources or capabilities | `meta` | 0.92 |
| 3 | Off-topic vocabulary (weather, stocks, recipes, …) and no in-scope vocabulary | `out_of_scope` | 0.88 |
| 4 | Anaphora ("那個", "it", …), earlier turns exist, message under 40 characters | `follow_up` | 0.85 |
| 5 | In-scope vocabulary (學程, 課程, TAICA, lab, …) | `knowledge` | 0.80 |

### 7.2 Routing

| Intent | Pipeline |
|---|---|
| `knowledge`, `follow_up` | `retrieval` → `answer` (tool already chosen by the planner) |
| `chitchat`, `meta`, `out_of_scope` | Fixed reply in the interface language; no subagents, no MCP call |

### 7.3 Subagents

| Subagent | Responsibility |
|---|---|
| `planner` (not a subagent) | Runs before the pipeline. Settles intent, tool, arguments and search queries in one call to `ROUTER_MODEL`; validates the tool against what the server advertised. |
| `retrieval` | Rewrites the question into 1–3 standalone queries (LLM; on failure a deterministic path that splices in remembered context and maps English terms to Chinese ones); calls the chosen tool; falls back to search if a listing comes back empty; performs the deep read. |
| `answer` | Refuses below the threshold; otherwise generates a cited answer (LLM) or builds one from cited excerpts (no LLM, or generation failed). |
| `summary` | Every 8 exchanges, folds older turns into a rolling summary (at most ~120 Chinese characters or 60 English words). Best-effort. |

### 7.4 Memory

| Tier | Content | Limit | Used for |
|---|---|---|---|
| Short-term | Recent turns | Last 6 exchanges (12 turns) | Every prompt |
| Working | Last topic, named entities, last sources | 12 entities | Resolving follow-ups |
| Long-term | Rolling summary | Refreshed every 8 exchanges | Keeping prompt size flat in long conversations |
| Persistence | Whole session as JSON | 200 turns | Sidebar, restore after reload |

### 7.5 Sequence of one turn

1. Classify the intent.
2. Route to a subagent pipeline. For fixed-reply intents, reply, save and stop.
3. Record the user's turn.
4. The planner's tool choice is already in `ctx.scratch["plan"]`.
5. `retrieval` rewrites the query, calls the tool over MCP, falls back to search if needed, and deep-reads if needed.
6. `answer` refuses, answers from excerpts, or generates a cited answer.
7. Update working memory (entities, topic, sources) and save the session.
8. If a summary is due, run `summary` and save again. The turn was already saved in step 7, so a failed summary cannot lose it.
9. Return the answer, intent, grounded flag, citations, trace and subagent list.

---

## 8. Retrieval and data pipeline

### 8.1 Crawl (`scripts/crawl_yzu.py`)

- Breadth-first search from 14 seed URLs on `https://ai.yzu.edu.tw`. The host
  must match (a leading `www.` is ignored).
- Allowed path prefixes: `article`, `news_list`, `news_detail`, `notice`,
  `teacher_list`, `teacher_detail`, `lab_list`, `lab_detail`,
  `instrument_list`, `instrument_detail`, `album_list`, `album_detail`,
  `download`.
- Only the `?page=` query parameter is kept. URLs with any other parameter are
  skipped, never stripped — stripping and then fetching would store one page's
  content under a URL that does not exist.
- 0.4 s delay after every request, including failed ones; 20 s timeout; TLS
  certificates verified; budget of 200 successful fetches by default.
- Pages with less than 100 characters of text are not saved, but their links
  are still followed.
- Extraction: navigation, header, footer, forms, scripts and menu elements
  are removed; each table row becomes one Markdown row; each text block is
  emitted once (tracked by element identity); repeated blocks longer than 200
  characters are dropped (matched on an interior window of normalised text);
  the site name is removed from either end of the page title.
- Output: `data/raw/{sha1}.json` with `{url, title, text, section}`.

Corpus of the retired site (now archived): 62 pages fetched, 0 left queued, 47 saved — `news_detail` 24,
`article` 13, `news_list` 4, `teacher_detail` 2, `notice` 1, `teacher_list` 1,
`home` 1, `download` 1.

### 8.2 Ingest (`src/server/ingest.py`)

- Split each page at `#`–`####` headings.
- Within a section, cut windows of 500 characters with 80 characters of
  overlap, preferring paragraph and sentence boundaries.
- Prefix each chunk with `Title > Heading` so a fragment keeps its context.
- Chunk id = first 16 hex digits of `sha1(url | text)`; duplicate ids dropped.
- Date = the first `YYYY-MM-DD` (or `YYYY年M月D日`) within the page's first 300
  characters.

Current index: 407 chunks across 51 pages (13 live, 38 archived). Nine retired pages were dropped outright once their content was found live under a Joomla category (catid=9, TAICA) that nothing on the site links to; every remaining archived page cites the centre's current home page, never a third-party archive.

### 8.3 Index (`src/server/store.py`)

| Arm | Implementation |
|---|---|
| Dense | `intfloat/multilingual-e5-small`, with `query:` / `passage:` prefixes, L2-normalised; stored in a persistent ChromaDB collection with cosine distance. |
| Lexical | BM25 (Okapi) over lower-cased ASCII words + jieba search-mode words + CJK character bigrams. |

`data/index/chunks.json` holds the chunk text for BM25 and lookups;
`data/index/manifest.json` holds the index metadata.

### 8.4 Search (`src/server/retriever.py`)

1. Take the top 12 dense and top 12 BM25 results.
2. Order them with reciprocal rank fusion (k = 60) and keep the top 5.
3. Score each kept chunk with a confidence in [0, 1]:
   `max(cosine similarity, fraction of the query's content words found in the chunk)`.
4. Return the 5 chunks sorted by confidence.

RRF decides *which* chunks are returned; confidence decides their order and
drives the refusal. RRF's top result always scores `1/(k+1)`, so it cannot be
used to decide whether to refuse. An optional cross-encoder rerank
(`BAAI/bge-reranker-v2-m3`) is available and disabled.

### 8.5 Client-side retrieval

The client searches 1–3 rewritten queries in parallel, merges results by
(URL, first 60 characters) keeping the best score, and keeps the top 5. A turn
is *grounded* when the best score is at least `MIN_SCORE`.

### 8.6 Calibration

`scripts/calibrate.py` scores 12 answerable and 6 off-topic questions and
places `MIN_SCORE` between the two groups. Current result:

| | Score |
|---|---|
| Lowest answerable | 0.8632 (median 0.8854) |
| Highest off-topic | 0.8439 (median 0.8377) |
| `MIN_SCORE` | 0.855 |
| Margin | 0.0229 |

Calibration must be re-run after every crawl; the boundary moves with the data.

---

## 9. Non-functional requirements

| ID | Area | Requirement and current status |
|---|---|---|
| NFR-01 | Performance | Retrieval p50 70 ms over the 15-question evaluation set (2026-09-10). One measured full turn with an LLM took 7.4 s, of which 99.6 % was three LLM calls and 27 ms the two MCP calls. |
| NFR-02 | Availability | A model is required and its absence is detected at startup, not mid-question. Within a turn, a failed rewrite falls back deterministically, a failed generation returns the sources, and a failed summary never loses the answered turn (it is saved first). No embedding model → BM25 only, reported on the badge. |
| NFR-03 | Honesty | Status and trace report the path actually taken (`llm` vs `rule-fallback`, `hybrid` vs `lexical`). |
| NFR-04 | Security | Session ids are validated before they are used as file names (path traversal). Chat input is length-limited. API keys live only in `.env`, which is gitignored. The crawler verifies TLS and stays on one host. There is **no authentication**: lab deployment only. |
| NFR-05 | Privacy | The display name is stored only in the browser's `localStorage`. Conversations are stored locally in `data/memory/`. Questions go to the configured LLM endpoint when one is configured. |
| NFR-06 | Concurrency | MCP tool calls run in worker threads, and one question fans out into parallel calls. Both expensive singletons — the ChromaDB client and the embedding model — are constructed exactly once under a lock. `lru_cache` is not sufficient: it does not serialise construction, and concurrent first use corrupted the Chroma client and silently downgraded the encoder to lexical-only. |
| NFR-07 | Portability | Python ≥ 3.11; no GPU; any OpenAI-compatible endpoint (OpenAI, Gemini, Ollama). Tested on macOS. |
| NFR-08 | Accessibility | Native `<dialog>` dialogs (keyboard focus, Esc). Animations respect `prefers-reduced-motion`. Layout adapts down to phone width (≤ 820 px). |
| NFR-09 | Maintainability | 23 unit tests, lint clean (ruff), evaluation and calibration scripts, no front-end build step. |

---

## 10. Configuration

All settings are read from `.env` (see `.env.example`). Names are
case-insensitive.

| Key | Code default | Deployed | Note |
|---|---|---|---|
| `LLM_MODE` | `auto` | `auto` | `auto` detects a usable key, `api` trusts it as given. A model is required either way. |
| `LLM_BASE_URL` | OpenAI | OpenAI | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | empty | set | Secret; never commit |
| `LLM_MODEL` | `gpt-4o-mini` | `gpt-4.1` | Answer generation |
| `ROUTER_MODEL` | empty | `gpt-4.1-mini` | Intent + tool + query rewriting, one call. Empty reuses `LLM_MODEL` — required when `LLM_BASE_URL` is not OpenAI |
| `LLM_TEMPERATURE` | 0.1 | 0.1 | |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | same | ~470 MB, cached locally |
| `ENABLE_RERANKER` | `false` | `false` | |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 500 / 80 | 500 / 80 | Re-ingest after changing |
| `TOP_K_FINAL` | 5 | 5 | |
| `MIN_SCORE` | 0.855 | **0.855** | **Must be re-calibrated after every crawl** |
| `MCP_TRANSPORT` | `stdio` | `stdio` | `stdio` \| `http` |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / 8100 | same | HTTP transport only |
| `CLIENT_PORT` | 8000 | 8000 | Web console |
| `MAX_HISTORY_TURNS` | 6 | 6 | Exchanges in the short-term tier |
| `SUMMARIZE_AFTER_TURNS` | 8 | 8 | Exchanges between summaries |

---

## 11. Known limitations and open issues

| ID | Issue | Impact | Proposed fix |
|---|---|---|---|
| OI-1 | The refusal margin is 0.0229, measured through the query-rewrite path over 19 in-scope and 8 off-topic questions in both languages. `multilingual-e5-small` scores even unrelated text at 0.75–0.85, so the usable band is narrow. | An unusual off-topic question could cross the threshold. | Score the top hit against the corpus's own background similarity instead of raw cosine. |
| OI-2 | The website uses CJK *compatibility* ideographs (e.g. 領 U+F9B4) that look identical to the characters users type (領 U+9818). 7 of 407 chunks, from 3 pages. | Keyword matching and the evaluation's answer-span check cannot see these facts; the one remaining evaluation miss. The dense arm partly masks it. | Map the compatibility ranges (U+F900–U+FAFF, U+2F800–U+2FA1F) to canonical characters at ingest and in query tokenisation. Not full NFKC, which would also turn `，` into `,`. |
| OI-3 | English questions depend on the LLM rewrite to reach the Chinese corpus. Raw English scores 0.77–0.84 whether relevant or not. | If the rewrite call fails, only the ~20 terms in the English→Chinese map keep retrieval working; an English question outside those topics would be refused. | Widen the map, or add a cross-encoder reranker (`bge-reranker-v2-m3` is strongly cross-lingual, ~2.2 GB) so English matches without translation. |
| OI-4 | One page (a research professor's publication list) is 46 % of the corpus. | Skews term statistics; still surfaces on loosely related English queries. | Cap or down-weight each document's share of the index. |
| OI-5 | The index is a point-in-time snapshot. | Site updates need a full re-crawl. | Incremental crawl with content hashing. |
| OI-6 | Traces are per request and are not stored with the session. | A restored conversation shows no trace for old turns. | Persist trace steps alongside turns. |
| OI-7 | Faithfulness of generated answers is checked by hand. | No automated guard against unsupported sentences. | RAGAS-style faithfulness scoring. |
| OI-8 | No automated tests for the orchestrator, tool selection or the web API. | Regressions there are caught only by manual demo runs. | Tests with a fake MCP connection. |
| OI-9 | No authentication. | Anyone who can reach the port can read and delete sessions. | Acceptable for a lab demo; add auth before any shared deployment. |
| OI-10 | PDF and Word attachments are not crawled. | Their content cannot be answered. | Add a document parser to the crawl. |

---

## 12. Verification

| Method | Covers | Result (2026-09-10) |
|---|---|---|
| Unit tests (`make test`, 23 tests) | Intent rules and routing in both languages, tokenisation and chunking, English→Chinese term mapping | All pass |
| Retrieval evaluation (`make eval`, 15 questions) | Right page in the top 5, rank, whether the retrieved text contains the fact | doc_hit@5 0.933 · doc_MRR 0.813 · answer_span@5 0.667 · p50 70 ms |
| Calibration (27 questions, scored through the rewrite path) | Separation of answerable and off-topic questions, both languages | Clean separation, margin 0.0229 |
| Server smoke test (`make smoke`) | Transport, tool listing, retrieval without an LLM | Pass |
| Scripted conversation (`make demo`) | Chit-chat, knowledge, follow-up, out-of-scope, meta | Pass |
| English end-to-end | The four English sample questions: intent decided by rule (0 ms), three different tools chosen, weather refused | Pass |
| Browser checks | Sidebar and sessions, dialogs, trace panel, language switch, phone layout, invalid session ids rejected with 400 | Pass |

---

## 13. Traceability to the position requirements

| The position asks for | Where it is | Requirements |
|---|---|---|
| Python | Client, server, crawler, tests | all |
| Agents and subagents | `src/client/planner.py` plus `src/client/agents/` — `retrieval`, `answer`, `summary` on a common `Subagent` base | FR-01 – FR-07 |
| Memory management | `src/client/memory.py` — three tiers plus persistence | FR-02, FR-10 |
| Multi-agent orchestration | `src/client/orchestrator.py` | all conversational FRs |
| Intent handling | `src/client/intent.py` | FR-02, FR-07, FR-08 |
| Router | `src/client/router.py` | FR-07, FR-08 |
| MCP | `src/server/app.py`, `src/client/mcp_session.py` | FR-03, FR-15 |

# Research Agent

A local-first research assistant. It takes a scoped research task, plans the steps, retrieves
public sources (Wikipedia, Hacker News, URLs and documents you provide), maps claims to stored
evidence, flags gaps and conflicts, and writes a Markdown report with source links.

Status: **Phase 7 (evaluation)**. Submit a research task in the browser, watch the plan and
stages run, and review the comparison matrix, findings, unknowns, conflicts, sources, report and
activity log. Everything runs offline and free by default (recorded sources, mock analysis), and
a repeatable evaluation suite checks it (results below). Phase 6 (LangGraph / Claude) is optional
and not started. See [docs/PLAN.md](docs/PLAN.md).

## Stack

- **Backend:** FastAPI + Pydantic, Python 3.12 (managed by [uv](https://docs.astral.sh/uv/)), SQLite via stdlib `sqlite3`
- **Frontend:** Next.js 16 + TypeScript + Tailwind
- **LLM:** mock mode only. No paid model or search API is used.

## Setup

Prerequisites: uv and Node 20+.

```bash
cp .env.example backend/.env           # then edit backend values
cd backend && uv sync
uv run uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend && npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev
```

Open http://localhost:3000 and use **Load example** for the recorded headless-CMS task.

## Using the app

- **New research task** (home page): topic, entities and attributes (the comparison matrix),
  other questions, URLs to read, `.txt`/`.md` documents, number of sources. Inputs are checked
  in the browser and again by the API.
- **Run page** (`/runs/{id}`): updates every 1.5 s while the run is active.
  - *Progress*: the five stages with their summaries and errors; a failed run shows **Resume**.
  - *Plan*: research questions and the source queries chosen.
  - *Comparison*: entity × attribute matrix (Supported / Community only / Conflicting / Unknown)
    with citations to the Sources list.
  - *Findings*, *Unknowns and gaps*, *Conflicts*: claims with their verbatim evidence.
  - *Sources*: every retrieved source with kind, retrieval and posting dates, license, excerpt.
  - *Report*: rendered or raw Markdown, **Copy Markdown**, **Download .md**. Raw HTML and images
    are never rendered, and only links to this run's stored sources are clickable.
  - *Activity log*: every tool call with status, result count, HTTP requests and duration.
- **Run history** on the home page lists past runs, newest first.

Uploaded documents and URLs you add are stored before search results, so the source limit never
drops them.

The database is created at `backend/data/research.sqlite3` on first start. Delete that folder to reset.

## Sources

All adapters live in [backend/app/sources/](backend/app/sources/), share one read-only
`HttpClient` (timeouts, per-host rate limit, bounded retries on 429/5xx/timeouts with
`Retry-After` honored, response size cap) and return normalized `SourceRecord`s with URL,
title, retrieved-at timestamp (UTC), excerpt, the exact normalized content and its SHA-256.

| Adapter | API | Kind | Notes |
|---|---|---|---|
| `WikipediaSource` | MediaWiki Action API | reference | `maxlag=5`, descriptive User-Agent, CC BY-SA 4.0 license on each record |
| `HackerNewsSource` | Algolia HN Search + HN Firebase API | community | Discussion opinion, not verified fact; usernames not stored; bounded comments |
| `UserUrlSource` | the URL you provide | user_url | Public IPs only, ports 80/443, robots.txt honored, ≤3 redirects re-checked, HTML/text only |
| `load_document` | uploaded file | document | `.txt` / `.md` only so far (PDF later) |

**Offline fixtures.** With `SOURCES_MODE=fixtures` (the default), requests are answered from
recorded responses in `backend/fixtures/http/`; anything not recorded fails with a clear error
instead of touching the network. Recorded files drop HN usernames (`author`, `by`) and keep
only the `content-type` header. To record real responses (makes live, rate-limited calls; needs
`HTTP_USER_AGENT` with your contact in `backend/.env`):

```bash
cd backend && uv run python -m scripts.record_fixtures "headless CMS" "Strapi" --hn "headless CMS"
```

Unit tests use the synthetic fixtures in `backend/tests/fixtures/http/` and never call live APIs.
An opt-in live smoke test runs with `RUN_LIVE_TESTS=1 uv run pytest`.

## Workflow

One orchestrator ([backend/app/workflows/engine.py](backend/app/workflows/engine.py)) runs five
stages in order. Each stage execution is a stored `research_steps` row, and the run state is
saved after every completed stage, so a failed run resumes from the stage that failed.

| Stage | Mock implementation |
|---|---|
| plan | One question per entity × attribute, plus your free-form questions; deduplicated Wikipedia / HN / URL queries |
| research | Search each query, fetch the top result in full, store sources round-robin across queries (dedupe by URL and content hash) |
| analyze | Purely extractive: copies sentences that name the entity and match the attribute's keywords, with exact offsets. Nothing found → an explicit unknown. Then rule-based conflict detection across sources (see below) |
| verify | Marks each claim supported / contradicted / unknown (rules below) |
| write | Markdown with summary, comparison matrix, findings, unknowns, conflicts and a source list built only from stored records, then the report evidence check |

## Evidence and verification

Every claim carries evidence spans: `source_record_id`, the verbatim `quote`, its character
offsets in the stored source text, and a stance (`supports` / `contradicts`). Claims also list
their `source_record_ids`.

**Verifier** ([verifier.py](backend/app/verification/verifier.py)), in order:
1. A span is valid only if its source is in this run and the quote is exactly the stored text at
   those offsets. Invalid spans are dropped and noted.
2. The claim text must be stated in a valid supporting quote, or the claim is **unknown**.
3. A contradicting span from a reference, user URL or document → **contradicted**.
4. A supporting span from a reference, user URL or document → **supported** (a Hacker News
   contradiction adds a "disputed in community discussion" note).
5. Hacker News evidence alone → **unknown** (community opinion, not verification).

**Conflict detection** ([conflicts.py](backend/app/verification/conflicts.py)) compares narrow,
comparable facts stated about each entity across different sources: license model (open source
vs proprietary, with negation), founding year, initial release year and headquarters. A
disagreement becomes one claim with both quotes. Values that legitimately vary, like prices
across plans, are not compared.

**Report evidence check** ([report_check.py](backend/app/verification/report_check.py)) runs on
every generated report before it is saved. It rejects the report (the write stage fails, the
run can be resumed) if any of these is true:
- a `[n]` citation has no listed source
- a listed URL isn't a stored source
- a source line shows a "posted" date the source doesn't state
- a quote isn't verbatim evidence from the cited source
- a finding isn't a supported claim, or a "Supported" matrix cell lacks matching evidence
- the body contains links or HTML

This is independent of the writer, so it also guards a future LLM writer.

**Limits** (backend/.env): `MAX_STEPS_PER_RUN`, `MAX_TOOL_CALLS_PER_RUN`, `MAX_SOURCES_PER_QUESTION`,
`MAX_SOURCES_PER_RUN`, `MAX_RUN_SECONDS`, plus per-request `max_sources`. Hitting one fails the run
with a clear message; resume continues where it stopped. Every tool call (including failures and
blocked requests) is logged with its HTTP request count and duration. Runs interrupted by a server
restart are marked failed at startup so they can be resumed.

**Try it offline** with the recorded demo task:

```bash
curl -s -X POST localhost:8000/api/runs -H 'content-type: application/json' \
  -d @docs/examples/headless-cms.json
curl -s localhost:8000/api/runs/<id>/report.md
```

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | API status, database status, LLM provider, sources mode |
| POST | `/api/documents` | Upload a `.txt`/`.md` file (multipart `file`, ≤1 MB); returns its `id` |
| POST | `/api/runs` | Start a run (202). Body: `topic`, optional `entities` (≤8), `attributes` (≤6), `questions` (≤5), `user_urls` (≤5), `document_ids` (≤5), `max_sources` (1–25) |
| GET | `/api/runs` | Run history, newest first |
| GET | `/api/runs/{id}` | Status, plan, steps, sources (excerpts, no full text), claims with evidence spans |
| GET | `/api/runs/{id}/tool-calls` | Activity log |
| POST | `/api/runs/{id}/resume` | Resume a failed run (202); 409 otherwise |
| GET | `/api/runs/{id}/report` | Latest report as JSON |
| GET | `/api/runs/{id}/report.md` | Latest report as a Markdown download |

Interactive docs: http://localhost:8000/docs

## Evaluation

```bash
cd backend && uv run python -m evals.run                # run and print results
cd backend && uv run python -m evals.run --update-docs  # also refresh the results below
```

Eight tasks in [backend/evals/tasks.py](backend/evals/tasks.py), each with expected outcomes
written from what the recorded sources actually say (for example: Wikipedia's Contentful
article says it was founded in 2013; Wikipedia has no article on Strapi, Directus or Payload).
Every task runs **twice**, each time in a fresh database, offline, with the mock analyst. A task
passes only if all its checks hold and both runs produce the same outcome.

| Task | Demonstrates |
|---|---|
| `cms-comparison` | Finding sources and building the 5 × 5 matrix; only Wikipedia-stated facts count as supported; irrelevant search hits are not cited |
| `cms-conflicting-document` | An uploaded note ("founded in 2011") is used and flagged as contradicting Wikipedia |
| `cms-overview` | Overview mode; a product with no article is still supported where an article names it |
| `topic-question` | A free-form question answered from the most relevant article while one source fails |
| `partial-source-failure` | Failed tool calls are logged, the run completes and the gap is marked unknown |
| `unsafe-and-unreachable-urls` | A private-address URL is blocked before any request; an unreachable one is logged |
| `no-sources` | A run with nothing to find fails cleanly at research, with no report |
| `limit-then-resume` | The tool-call limit stops a run; resume finishes it without redoing the plan |

**Metrics** (recomputed from the stored database, not taken from the stages' own summaries):
- **Task completion**: tasks meant to complete that did complete.
- **Unsupported-claim rate**: supported or contradicted claims that fail an independent
  re-verification against the stored source text, or that lack a Wikipedia, URL or document
  quote. Should be 0.
- **Report evidence-check problems**: problems the report check finds in each saved report
  (citations, URLs, quotes, dates, links). Should be 0.
- **Repeatable**: both runs of a task produce the same sources, claims and report.
- **Error scenarios handled**: the failure tasks behave exactly as expected.
- **Per task**: sources stored, *entity coverage* (entities named in at least one stored source),
  *cells with evidence* (matrix cells with any quote, including community-only), supported cells,
  claims by status, tool calls (failed / blocked).

The pytest suite runs the evaluation too (`tests/test_evals.py`), and also checks that it catches
a broken agent: a verifier that marks everything supported, and a writer that adds a fake source.
Per-check detail: [docs/evaluation.md](docs/evaluation.md).

### Results

<!-- eval:start -->
**8 of 8 tasks passed** (91 of 91 checks; each task run twice, offline, mock analysis).

| Metric | Result |
|---|---|
| Task completion (tasks meant to complete) | 7 of 7 |
| Unsupported-claim rate | 0 of 16 supported/contradicted claims (0%) |
| Report evidence-check problems | 0 |
| Repeatable (identical outcome on rerun) | 8 of 8 |
| Error scenarios handled as expected | 5 of 5 |

| Task | Result | Sources | Entity coverage | Cells with evidence | Supported cells | Claims (S / C / U) | Tool calls (failed / blocked) |
|---|---|---|---|---|---|---|---|
| `cms-comparison` | pass: completed | 15 | 100% | 68% | 2 of 25 | 2 / 0 / 27 | 24 (0 / 0) |
| `cms-conflicting-document` | pass: completed | 15 | 100% | 68% | 2 of 25 | 2 / 1 / 27 | 25 (0 / 0) |
| `cms-overview` | pass: completed | 15 | 100% | 100% | 2 of 2 | 3 / 0 / 1 | 12 (0 / 0) |
| `topic-question` | pass: completed | 5 | — | — | — | 3 / 0 / 0 | 3 (1 / 0) |
| `partial-source-failure` | pass: completed | 15 | 50% | 50% | 1 of 2 | 1 / 0 / 1 | 10 (2 / 0) |
| `unsafe-and-unreachable-urls` | pass: completed | 10 | — | — | — | 3 / 0 / 0 | 6 (1 / 1) |
| `no-sources` | pass: failed (research) | 0 | — | — | — | 0 / 0 / 0 | 2 (2 / 0) |
| `limit-then-resume` | pass: completed | 15 | 100% | 100% | 1 of 1 | 1 / 0 / 0 | 10 (0 / 0) |
<!-- eval:end -->

**Reading the results.** The agent is reliable about *what it claims*: no unsupported claims, no
report problems, identical reruns. It is limited in *what it can find*: in the main comparison
only 2 of 25 cells are supported, because Wikipedia has no articles for most of these products
and the mock analyst only quotes, never infers. Most cells have community-only evidence (Hacker
News) or none, and the report says so instead of filling the gaps. Better coverage needs more
sources (your URLs or documents) or a model-based analyst (Phase 6), with the same verifier and
report check in front of it.

## Checks

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

## Data model

Tables are created in [backend/app/repositories/db.py](backend/app/repositories/db.py):
`research_runs`, `research_steps`, `tool_calls` (activity log), `source_records`,
`source_contents` (the exact retrieved text), `claims`, `evidence_spans` (quote and offsets
into the source content), and `reports`. A claim counts as supported only when an evidence span
quotes text that really appears in a stored source.

## Safety

- Read-only retrieval from public APIs, within their rate limits. Wikipedia requests carry a
  descriptive User-Agent (set `HTTP_USER_AGENT` before live mode).
- Retrieved text is treated as untrusted data, never as instructions.
- Citations come only from stored source records. Unsupported claims are marked unknown.
- Limits on steps, sources, request time and run time are configured in `.env`.

## Limitations

- The mock analyst only finds sentences that literally name an entity and an attribute keyword;
  it does not summarize or paraphrase. Conflict detection only covers the four facts above.
  For the demo task most cells end up *Unknown* or *community only*. That's the honest result
  for what Wikipedia and Hacker News actually say, not a bug.
- Runs execute in-process (FastAPI background tasks); there is no job queue.
- The recorded demo task has no cross-source conflicts on its own: each product fact comes from
  at most one Wikipedia article. Add a document or URL that disagrees (for example a note saying
  "Contentful was founded in 2011") to see one.
- The report numbers citations in citation order; the run page numbers sources in list order.
  Each view's `[n]` refers to its own source list.
- No general web search: only Wikipedia, Hacker News, and URLs/documents you supply.
- Recorded fixtures cover one headless-CMS task (Wikipedia: headless CMS, headless content
  management system, Strapi, Contentful, Sanity CMS, Directus, Payload CMS; HN: headless CMS,
  Strapi, Contentful, Sanity CMS, Directus, Payload CMS),
  recorded 2026-11-13. Wikipedia search returns some off-topic pages for product names; that is
  real API behavior, kept on purpose.
- URL safety checks resolve DNS before the request, so a hostile DNS server could rebind in
  between. Acceptable for a local tool you drive yourself.

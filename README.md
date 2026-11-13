# Research Agent

A local-first research assistant. It takes a scoped research task, plans the steps, retrieves
public sources (Wikipedia, Hacker News, URLs and documents you provide), maps claims to stored
evidence, flags gaps and conflicts, and writes a Markdown report with source links.

Status: **Phase 3 (workflow engine)**. Research runs execute end to end over the API in mock
mode, offline by default. The research UI comes in Phase 5. See [docs/PLAN.md](docs/PLAN.md).

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

Open http://localhost:3000. The page shows whether the API and database are reachable.

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
| analyze | Purely extractive: copies sentences that name the entity and match the attribute's keywords, with exact offsets. Nothing found → an explicit unknown |
| verify | Drops any span whose quote isn't at those offsets in the stored source. *Supported* needs a non-community source; Hacker News only → unknown |
| write | Markdown with comparison matrix, findings, unknowns, conflicts, and a source list built only from stored records |

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
| POST | `/api/runs` | Start a run (202). Body: `topic`, optional `entities` (≤8), `attributes` (≤6), `questions` (≤5), `user_urls` (≤5), `max_sources` (1–25) |
| GET | `/api/runs` | Run history, newest first |
| GET | `/api/runs/{id}` | Status, plan, steps, sources (excerpts, no full text), claims with evidence spans |
| GET | `/api/runs/{id}/tool-calls` | Activity log |
| POST | `/api/runs/{id}/resume` | Resume a failed run (202); 409 otherwise |
| GET | `/api/runs/{id}/report` | Latest report as JSON |
| GET | `/api/runs/{id}/report.md` | Latest report as a Markdown download |

Interactive docs: http://localhost:8000/docs

## Checks

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run lint && npm run build
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
  it does not summarize, paraphrase or detect contradictions (Phase 4 adds contradiction checks).
  For the demo task most cells end up *Unknown* or *community only*. That's the honest result
  for what Wikipedia and Hacker News actually say, not a bug.
- Runs execute in-process (FastAPI background tasks); there is no job queue.
- No general web search: only Wikipedia, Hacker News, and URLs/documents you supply.
- Recorded fixtures cover one headless-CMS task (Wikipedia: headless CMS, headless content
  management system, Strapi, Contentful, Sanity CMS, Directus, Payload CMS; HN: headless CMS,
  Strapi, Contentful, Sanity CMS, Directus, Payload CMS),
  recorded 2026-11-13. Wikipedia search returns some off-topic pages for product names; that is
  real API behavior, kept on purpose.
- URL safety checks resolve DNS before the request, so a hostile DNS server could rebind in
  between. Acceptable for a local tool you drive yourself.

# Research Agent

A local-first research assistant. It takes a scoped research task, plans the steps, retrieves
public sources (Wikipedia, Hacker News, URLs and documents you provide), maps claims to stored
evidence, flags gaps and conflicts, and writes a Markdown report with source links.

Status: **Phase 2 (source adapters)**. The API serves a health check and creates the SQLite
schema; the source adapters are implemented and tested. The workflow and research UI come in
later phases. See
[docs/PLAN.md](docs/PLAN.md).

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
instead of touching the network. To record real responses (makes live, rate-limited calls; needs
`HTTP_USER_AGENT` with your contact in `backend/.env`):

```bash
cd backend && uv run python -m scripts.record_fixtures "headless CMS" "Strapi" --hn "headless CMS"
```

Unit tests use the synthetic fixtures in `backend/tests/fixtures/http/` and never call live APIs.
An opt-in live smoke test runs with `RUN_LIVE_TESTS=1 uv run pytest`.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | API status, database status, LLM provider, sources mode |

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

- No research workflow yet (Phase 3); adapters are not exposed over the API.
- No general web search: only Wikipedia, Hacker News, and URLs/documents you supply.
- `backend/fixtures/http/` is empty until you record fixtures.
- URL safety checks resolve DNS before the request, so a hostile DNS server could rebind in
  between. Acceptable for a local tool you drive yourself.

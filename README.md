# Research Agent

A local-first research assistant. It takes a scoped research task, plans the steps, retrieves
public sources (Wikipedia, Hacker News, URLs and documents you provide), maps claims to stored
evidence, flags gaps and conflicts, and writes a Markdown report with source links.

Status: **Phase 1 (scaffold)**. The API serves a health check and creates the SQLite schema.
Source adapters, the workflow, and the research UI come in later phases. See
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

Phase 1 only. There is no research workflow yet.

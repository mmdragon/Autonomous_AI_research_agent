# Phase 0 Plan — Autonomous Research Agent

Source docs: `../PROJECT_BRIEF.md`, `../ARCHITECTURE.md`, `../BUILD_PROMPTS.md`.
Conventions follow Project2 (uv + Python 3.12, FastAPI/Pydantic, ruff, pytest; Next.js + TS, npm).

## Workspace state

Only the three brief docs exist. No code, no git repo yet. Local toolchain: Node 22, uv, npm.
System Python is 3.9, so the backend pins 3.12 through uv (`.python-version`).

## Phased plan

| Phase | Deliverable | Done when |
|---|---|---|
| 1 Scaffold | `research-agent/` with `frontend/` (Next.js + TS) and `backend/` (FastAPI, Pydantic, pydantic-settings, SQLite via stdlib `sqlite3` + repository layer), `/health`, `.env.example`, `.gitignore`, README, `git init` | `uv run pytest` and `npm run build` pass; `/health` returns ok |
| 2 Source adapters | `SearchSource` protocol; Wikipedia, Hacker News (Algolia search + Firebase item), user URL, local document adapters; shared HTTP client with timeout, retry on 429/5xx only, per-host rate limiter, size cap | Fixture-based tests pass with no network; one opt-in live smoke test |
| 3 Workflow engine | Explicit state machine `plan → research → analyze → verify → write`, each stage persisted as `ResearchStep`; limits on steps, sources/question, wall time; resume from failed stage; mock LLM provider | Mock run completes offline end-to-end; limit and failure tests pass |
| 4 Evidence & verification | `Claim` + `EvidenceSpan` mapping; verifier marks supported / contradicted / unknown; writer renders citations only from DB records | Every report citation resolves to a stored source; tests for mapping |
| 5 Frontend | Task form, live plan + step status, sources list, comparison matrix, unknowns/conflicts, report view + copy/download `.md`, run history, activity log | Accessible loading/error/empty states; works against mock mode |
| 6 Optional | LangGraph port and/or Claude provider, after a cost and credential review | Mock mode and adapters still pass tests |
| 7 Evaluation | 5–8 repeatable tasks with expected evidence outcomes; metrics: source coverage, unsupported-claim rate, completion, run errors | Results recorded in README |

## API terms and rate limits to check (and how we comply)

**Wikipedia / Wikimedia**
- Action API (`/w/api.php`, `list=search`, `prop=extracts`) and REST (`/api/rest_v1/page/summary/{title}`).
- API etiquette requires a descriptive `User-Agent` with a contact. We make this a required
  `.env` setting (`HTTP_USER_AGENT`) rather than hard-coding anyone's details.
- Make requests serially, send `maxlag=5` on action API calls, back off on `Retry-After`.
  REST endpoints document about 200 req/s; we self-limit far below (~1 req/s).
- Content is CC BY-SA 4.0: reports must credit the article title + URL and note the license.

**Hacker News**
- Official Firebase API (`hacker-news.firebaseio.com/v0`) has no search and no stated rate limit.
- Search uses the Algolia HN Search API (`hn.algolia.com/api/v1/search`), a third-party service
  documented at 10,000 requests/hour per IP. We cap at ~1 req/s and cache by query.
- HN comments are user opinion: tagged `source_kind=community`, never treated as verified fact on
  their own.

**User-provided URLs and documents**
- Fetch only URLs the user typed into the task. Check `robots.txt`, GET only, no auth/cookies,
  follow at most 3 redirects, allow `text/html`, `text/plain`, `application/pdf` only, 2 MB cap.
- Block private/loopback/link-local IPs to prevent SSRF.
- Uploads: `.md`, `.txt`, `.pdf` (pymupdf), size-capped, stored locally.

No general web-search API is assumed. Search providers stay replaceable behind `SearchSource`.

## How evidence and citations are stored

1. **SourceRecord**: `id, run_id, url, title, source_name, source_kind (reference | community |
   user_url | document), retrieved_at (UTC), excerpt, content_hash (sha256 of normalized text),
   license, published_at (only if the source states it; never inferred)`.
2. **SourceContent**: the normalized retrieved text (bounded size), kept separately so the
   verifier can check quotes against exactly what was fetched. Same hash means dedupe.
3. **Claim**: `id, run_id, entity, attribute, claim_text, claim_type (fact | analysis),
   verification_status (supported | contradicted | unknown), notes`.
4. **EvidenceSpan**: `id, claim_id, source_record_id, quote, start, end, stance (supports | contradicts)`.
   A span is valid only if `quote` appears verbatim at those offsets in `SourceContent`, which
   the verifier checks mechanically. This is how "no citation without a source record" becomes
   enforceable rather than a convention.
5. **Writer**: receives claim IDs only. Citation markers `[n]` and the reference list are
   rendered from `SourceRecord` rows, so the writer (mock or LLM) can't produce a URL.
   Facts without a supported span go in "Unverified / unknown"; contradicting spans go in
   "Conflicts". Analysis is labeled as analysis.
6. Retrieved text is wrapped as data (delimited, never concatenated into instructions) and
   stripped of markup before any LLM step.

## Mock mode

- `LLM_PROVIDER=mock`: rule-based planner (question templates per entity and attribute), keyword
  and sentence-window claim extraction, template writer. Deterministic.
- `SOURCES_MODE=fixtures|live`: fixtures replay recorded API responses, so the whole demo runs offline.

## Defaults chosen (change any before Phase 1)

- SQLite through a thin repository layer with plain `sqlite3`, no ORM, matching the brief's simplicity.
- Background runs through FastAPI `BackgroundTasks` plus polling from the UI (no queue or websockets yet).
- Limits: 12 steps per run, 5 sources per question, 25 sources per run, 30 s HTTP timeout,
  3 retry attempts with exponential backoff, 5 min run wall-clock.

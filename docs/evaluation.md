# Evaluation results

Generated 2026-11-13 23:31 UTC by `uv run python -m evals.run --update-docs` (backend/). Offline: recorded Wikipedia and Hacker News responses (2026-11-13), mock analysis, no network or API keys.

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

## Tasks and checks

### `cms-comparison`: Compare five headless CMS products

*Finds sources, builds the matrix, supports only what Wikipedia states.*


- ✅ status is completed
- ✅ report saved = True
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 10 sources (15)
- ✅ ≤ 15 sources (15)
- ✅ ≥ 3 reference source(s) (6)
- ✅ ≥ 3 community source(s) (9)
- ✅ cites 'Contentful'
- ✅ does not cite 'Atlantic jackknife clam'
- ✅ does not cite 'GSAT-7R'
- ✅ Contentful / integrations is supported (supported)
- ✅ Contentful / API options is supported (supported)
- ✅ Contentful / pricing is unknown (unknown)
- ✅ Directus / API options is community (community)
- ✅ nothing about Strapi marked supported (0 supported)
- ✅ nothing about Directus marked supported (0 supported)
- ✅ nothing about Payload CMS marked supported (0 supported)
- ✅ ≤ 0 conflicts (0)
- ✅ ≥ 2 supported claim(s) (2)
- ✅ entity coverage ≥ 100% (100%)
- ✅ ≤ 0 failed tool calls (0)
- ✅ identical outcome on a second run (fingerprint `cd7ca5797faa8b2a`)

### `cms-conflicting-document`: Same comparison plus a team note that disagrees with Wikipedia

*Uses an uploaded document and flags a cross-source contradiction.*

Uploaded documents: team-notes.md.

- ✅ status is completed
- ✅ report saved = True
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 10 sources (15)
- ✅ ≥ 1 document source(s) (1)
- ✅ cites 'Contentful'
- ✅ cites 'team-notes.md'
- ✅ nothing about Strapi marked supported (0 supported)
- ✅ nothing about Directus marked supported (0 supported)
- ✅ nothing about Payload CMS marked supported (0 supported)
- ✅ conflict: Contentful founding year contradicted (contradicted)
- ✅ ≤ 0 failed tool calls (0)
- ✅ identical outcome on a second run (fingerprint `bbe5879386c24b47`)

### `cms-overview`: Overview of two products, no attributes

*Overview mode: Strapi has no Wikipedia article, but the headless CMS article names it, and that sentence is enough to support an overview.*


- ✅ status is completed
- ✅ report saved = True
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 4 sources (15)
- ✅ cites 'Headless content management system'
- ✅ Contentful / overview is supported (supported)
- ✅ Strapi / overview is supported (supported)
- ✅ entity coverage ≥ 100% (100%)
- ✅ ≤ 0 failed tool calls (0)
- ✅ identical outcome on a second run (fingerprint `73b9bb69416acea0`)

### `topic-question`: Topic only: what is a headless CMS?

*Free-form question answered from the most relevant article, despite one source failing.*


- ✅ status is completed
- ✅ report saved = True
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 3 sources (5)
- ✅ cites 'Headless content management system'
- ✅ ≥ 1 supported claim(s) (3)
- ✅ ≥ 1 failed tool call(s) logged (1)
- ✅ ≤ 1 failed tool calls (1)
- ✅ identical outcome on a second run (fingerprint `fbdbd24af91c8640`)

### `partial-source-failure`: One entity has no retrievable sources

*Failed tool calls are logged; the run completes and marks the gap unknown.*


- ✅ status is completed
- ✅ report saved = True
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 3 sources (15)
- ✅ Contentful / integrations is supported (supported)
- ✅ Nonexistent CMS 9000 / integrations is unknown (unknown)
- ✅ nothing about Nonexistent CMS 9000 marked supported (0 supported)
- ✅ ≥ 2 failed tool call(s) logged (2)
- ✅ identical outcome on a second run (fingerprint `3e014d1276ac5592`)

### `unsafe-and-unreachable-urls`: User URLs: a private address and an unrecorded page

*Unsafe URL blocked before any request; unreachable URL logged; run completes.*


- ✅ status is completed
- ✅ report saved = True
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 3 sources (10)
- ✅ ≥ 1 failed tool call(s) logged (1)
- ✅ ≥ 1 blocked call(s) (1)
- ✅ identical outcome on a second run (fingerprint `3b4ecedeadf96936`)

### `no-sources`: Topic with nothing to find

*Fails cleanly at research with a clear message and no report.*


- ✅ status is failed (research failed: No sources retrieved (2 of 2 queries failed))
- ✅ research stage failed (research)
- ✅ error mentions 'No sources retrieved' (research failed: No sources retrieved (2 of 2 queries failed))
- ✅ report saved = False
- ✅ report passes evidence check
- ✅ no unsupported claims (0 found)
- ✅ ≥ 2 failed tool call(s) logged (2)
- ✅ identical outcome on a second run (fingerprint `5d28a90f4498a814`)

### `limit-then-resume`: Tool-call limit stops the run; resume finishes it

*Workflow limits are enforced and a failed run resumes without redoing work.*

Settings: {'max_tool_calls_per_run': 2}.

- ✅ first attempt: status is failed (research failed: Tool call limit reached (2))
- ✅ first attempt: research stage failed (research)
- ✅ first attempt: error mentions 'Tool call limit reached (2)' (research failed: Tool call limit reached (2))
- ✅ first attempt: report saved = False
- ✅ first attempt: report passes evidence check
- ✅ first attempt: no unsupported claims (0 found)
- ✅ after resume: status is completed
- ✅ after resume: report saved = True
- ✅ after resume: report passes evidence check
- ✅ after resume: no unsupported claims (0 found)
- ✅ after resume: ≥ 3 sources (15)
- ✅ after resume: Contentful / integrations is supported (supported)
- ✅ after resume: ≤ 0 failed tool calls (0)
- ✅ after resume: plan not repeated (1)
- ✅ identical outcome on a second run (fingerprint `5803748ee6413d25`)


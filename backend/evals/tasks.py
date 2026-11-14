"""Repeatable evaluation tasks with expected outcomes.

All tasks run offline against the recorded fixtures in backend/fixtures/http (real Wikipedia
and Hacker News responses recorded 2026-11-13) with the mock analyst. Expected outcomes are
written from what those sources actually say, for example:
- Wikipedia has a Contentful article, so Contentful facts can be *supported*;
- Wikipedia has no article for Strapi, Directus or Payload (their searches return unrelated
  pages), so their cells can at best be *community only*, never supported;
- the Contentful article states it was "founded in 2013".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.research import ResearchRequest

CMS = ["Strapi", "Contentful", "Sanity CMS", "Directus", "Payload CMS"]
ATTRIBUTES = ["content modeling", "API options", "integrations", "developer experience", "pricing"]
NO_WIKIPEDIA_ARTICLE = ["Strapi", "Directus", "Payload CMS"]


@dataclass
class Expect:
    status: str = "completed"
    failed_stage: str | None = None
    error_contains: str | None = None
    min_sources: int = 0
    max_sources: int | None = None
    source_kinds: dict[str, int] = field(default_factory=dict)  # kind -> minimum count
    cited_titles: list[str] = field(default_factory=list)  # in the report's source list
    not_cited_titles: list[str] = field(default_factory=list)
    cells: dict[str, str] = field(default_factory=dict)  # "Entity|attribute" -> status
    never_supported_entities: list[str] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)  # entity, attribute, status
    max_conflicts: int | None = None
    min_supported_claims: int = 0
    min_entity_coverage: float | None = None
    min_tool_errors: int = 0
    max_tool_errors: int | None = None
    min_tool_blocked: int = 0
    report: bool = True


@dataclass
class EvalTask:
    id: str
    title: str
    purpose: str  # what the task demonstrates
    request: ResearchRequest
    expect: Expect
    documents: dict[str, str] = field(default_factory=dict)  # filename -> text
    settings: dict[str, Any] = field(default_factory=dict)  # Settings overrides for the run
    resume_expect: Expect | None = None  # resume with default settings, then check this


TASKS: list[EvalTask] = [
    EvalTask(
        id="cms-comparison",
        title="Compare five headless CMS products",
        purpose="Finds sources, builds the matrix, supports only what Wikipedia states",
        request=ResearchRequest(
            topic="headless CMS", entities=CMS, attributes=ATTRIBUTES, max_sources=15
        ),
        expect=Expect(
            min_sources=10,
            max_sources=15,
            source_kinds={"reference": 3, "community": 3},
            cited_titles=["Contentful"],
            not_cited_titles=["Atlantic jackknife clam", "GSAT-7R"],
            cells={
                "Contentful|integrations": "supported",
                "Contentful|API options": "supported",
                "Contentful|pricing": "unknown",
                "Directus|API options": "community",
            },
            never_supported_entities=NO_WIKIPEDIA_ARTICLE,
            max_conflicts=0,
            min_supported_claims=2,
            min_entity_coverage=1.0,
            max_tool_errors=0,
        ),
    ),
    EvalTask(
        id="cms-conflicting-document",
        title="Same comparison plus a team note that disagrees with Wikipedia",
        purpose="Uses an uploaded document and flags a cross-source contradiction",
        request=ResearchRequest(
            topic="headless CMS", entities=CMS, attributes=ATTRIBUTES, max_sources=15
        ),
        documents={
            "team-notes.md": "# Team notes\n\nContentful was founded in 2011 in Berlin, "
            "according to our notes.\n"
        },
        expect=Expect(
            min_sources=10,
            source_kinds={"document": 1},
            cited_titles=["Contentful", "team-notes.md"],
            conflicts=[
                {"entity": "Contentful", "attribute": "founding year", "status": "contradicted"}
            ],
            never_supported_entities=NO_WIKIPEDIA_ARTICLE,
            max_tool_errors=0,
        ),
    ),
    EvalTask(
        id="cms-overview",
        title="Overview of two products, no attributes",
        purpose="Overview mode: Strapi has no Wikipedia article, but the headless CMS article "
        "names it, and that sentence is enough to support an overview",
        request=ResearchRequest(topic="headless CMS", entities=["Contentful", "Strapi"]),
        expect=Expect(
            min_sources=4,
            cells={"Contentful|overview": "supported", "Strapi|overview": "supported"},
            cited_titles=["Headless content management system"],
            min_entity_coverage=1.0,
            max_tool_errors=0,
        ),
    ),
    EvalTask(
        id="topic-question",
        title="Topic only: what is a headless CMS?",
        purpose="Free-form question answered from the most relevant article, despite one "
        "source failing",
        request=ResearchRequest(topic="headless content management system"),
        # Hacker News was only recorded for "headless CMS", so its search fails offline: the
        # run must log that and still answer from Wikipedia.
        expect=Expect(
            min_sources=3,
            cited_titles=["Headless content management system"],
            min_supported_claims=1,
            min_tool_errors=1,
            max_tool_errors=1,
        ),
    ),
    EvalTask(
        id="partial-source-failure",
        title="One entity has no retrievable sources",
        purpose="Failed tool calls are logged; the run completes and marks the gap unknown",
        request=ResearchRequest(
            topic="headless CMS",
            entities=["Contentful", "Nonexistent CMS 9000"],
            attributes=["integrations"],
        ),
        expect=Expect(
            min_sources=3,
            cells={
                "Contentful|integrations": "supported",
                "Nonexistent CMS 9000|integrations": "unknown",
            },
            never_supported_entities=["Nonexistent CMS 9000"],
            min_tool_errors=2,
        ),
    ),
    EvalTask(
        id="unsafe-and-unreachable-urls",
        title="User URLs: a private address and an unrecorded page",
        purpose="Unsafe URL blocked before any request; unreachable URL logged; run completes",
        request=ResearchRequest(
            topic="headless CMS",
            user_urls=["http://127.0.0.1/admin", "https://example.com/pricing"],
        ),
        expect=Expect(min_sources=3, min_tool_blocked=1, min_tool_errors=1),
    ),
    EvalTask(
        id="no-sources",
        title="Topic with nothing to find",
        purpose="Fails cleanly at research with a clear message and no report",
        request=ResearchRequest(topic="quantum gardening"),
        expect=Expect(
            status="failed",
            failed_stage="research",
            error_contains="No sources retrieved",
            min_tool_errors=2,
            report=False,
        ),
    ),
    EvalTask(
        id="limit-then-resume",
        title="Tool-call limit stops the run; resume finishes it",
        purpose="Workflow limits are enforced and a failed run resumes without redoing work",
        request=ResearchRequest(
            topic="headless CMS", entities=["Contentful"], attributes=["integrations"]
        ),
        settings={"max_tool_calls_per_run": 2},
        expect=Expect(
            status="failed",
            failed_stage="research",
            error_contains="Tool call limit reached (2)",
            report=False,
        ),
        resume_expect=Expect(
            min_sources=3, cells={"Contentful|integrations": "supported"}, max_tool_errors=0
        ),
    ),
]

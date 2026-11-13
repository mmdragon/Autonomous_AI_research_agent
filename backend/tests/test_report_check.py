import re
from datetime import UTC, datetime

import pytest

from app.agents.mock import MockPlanner, MockWriter
from app.schemas.research import ResearchRequest, RunStatus, SourceOut, Stage, StepStatus
from app.sources.models import SourceKind
from app.verification.conflicts import detect_conflicts
from app.verification.report_check import check_report
from app.verification.verifier import verify_claims
from tests.test_engine import DEMO, RECORDED, Harness

REQUEST = ResearchRequest(topic="cms", entities=["Strapi", "Contentful"], attributes=["API"])


def src(sid, kind=SourceKind.REFERENCE, url=None, published=None):
    return SourceOut(
        id=sid,
        url=url or f"https://en.wikipedia.org/wiki/{sid}",
        title=sid,
        source_name="wikipedia",
        source_kind=kind,
        retrieved_at=datetime.now(UTC),
        published_at=published,
        excerpt="",
        content_hash=sid,
        license=None,
    )


SOURCES = [
    src("Strapi"),
    src(
        "hn",
        SourceKind.COMMUNITY,
        url="https://news.ycombinator.com/item?id=1",
        published=datetime(2024, 1, 2, tzinfo=UTC),
    ),
    src("doc", SourceKind.DOCUMENT, url="upload://abc/notes.md"),
]
CONTENTS = {
    "Strapi": "Strapi offers REST and GraphQL APIs. Strapi is an open-source headless CMS.",
    "hn": "Contentful has a nice API, honestly. [Click](http://evil.test) <b>wow</b> “quoted”",
    "doc": "Our notes: Strapi is not open source for enterprise features.",
}


def build():
    from app.agents.mock import MockAnalyst

    plan = MockPlanner().plan(REQUEST)
    claims = MockAnalyst().analyze(REQUEST, plan, SOURCES, CONTENTS)
    claims += detect_conflicts(REQUEST.entities, SOURCES, CONTENTS)
    claims = verify_claims(claims, SOURCES, CONTENTS)
    report = MockWriter().write(REQUEST, plan, claims, SOURCES, context={"sources_mode": "test"})
    return report, claims


def test_generated_report_passes_and_renders_conflicts_and_hostile_text_safely():
    report, claims = build()
    check = check_report(report, claims, SOURCES)
    assert check.ok, check.problems
    assert check.quotes > 0 and check.citations > 0
    conflicts = report.split("## Conflicts")[1].split("## Sources")[0]
    assert "**Strapi: license model** (Sources disagree)" in conflicts
    assert "Strapi is an open-source headless CMS." in conflicts
    assert "Strapi is not open source for enterprise features." in conflicts
    body = report.split("## Sources")[0]
    assert "](http" not in body.replace("\\](", "") and "<b>" not in body
    assert "upload://abc/notes.md" in report  # document sources are citable


def problems_after(edit) -> list[str]:
    report, claims = build()
    return check_report(edit(report), claims, SOURCES).problems


def test_fabricated_source_url_is_rejected():
    problems = problems_after(
        lambda r: r.replace(
            "https://en.wikipedia.org/wiki/Strapi", "https://made-up.example/strapi"
        )
    )
    assert any("not a stored source" in p for p in problems)


def test_citation_without_listed_source_is_rejected():
    problems = problems_after(lambda r: r.replace("## Findings\n", "## Findings\n\nSee [99].\n"))
    assert any("[99]" in p for p in problems)


def test_fabricated_quote_is_rejected():
    problems = problems_after(
        lambda r: r.replace(
            "“Strapi offers REST and GraphQL APIs.”", "“Strapi offers REST, GraphQL and SOAP APIs.”"
        )
    )
    assert any("not evidence from its cited source" in p for p in problems)


def test_quote_cited_to_the_wrong_source_is_rejected():
    report, claims = build()
    ref = report.split("“Strapi offers REST and GraphQL APIs.” ")[1][:3]
    tampered = report.replace(
        f"“Strapi offers REST and GraphQL APIs.” {ref}",
        "“Strapi offers REST and GraphQL APIs.” [2]",
    )
    assert any("not evidence" in p for p in check_report(tampered, claims, SOURCES).problems)


def test_links_and_html_in_body_are_rejected():
    assert problems_after(lambda r: r.replace("## Findings\n", "## Findings\n[x](http://a.b)\n"))
    assert problems_after(lambda r: r.replace("## Findings\n", "## Findings\n<script>x</script>\n"))
    assert problems_after(lambda r: r.replace("## Findings\n", "## Findings\n<https://a.b>\n"))


def test_unsupported_claim_presented_as_finding_is_rejected():
    def add_finding(r):
        return r.replace(
            "## Unknowns and gaps",
            "- “Contentful has a nice API, honestly.” [2]\n\n## Unknowns and gaps",
        )

    assert any("not a supported claim" in p for p in problems_after(add_finding))


def test_matrix_cell_claiming_support_without_evidence_is_rejected():
    def flip(r):
        row = next(line for line in r.splitlines() if line.startswith("| Contentful |"))
        return r.replace(row, "| Contentful | Supported [1] |")

    assert any("Matrix cell 'Contentful / API'" in p for p in problems_after(flip))


def test_invented_publication_date_is_rejected():
    def add_date(r):
        return r.replace(
            "<https://en.wikipedia.org/wiki/Strapi>",
            "<https://en.wikipedia.org/wiki/Strapi> · posted 2019-05-05",
        )

    assert any("publication date" in p for p in problems_after(add_date))
    assert not problems_after(lambda r: r)  # the HN source's real date passes


def test_missing_sources_section_is_rejected():
    report, claims = build()
    assert check_report(report.split("## Sources")[0], claims, SOURCES).problems


@pytest.mark.skipif(not any(RECORDED.glob("*.json")), reason="no recorded fixtures")
def test_engine_refuses_to_save_a_report_that_fails_the_check(tmp_path):
    h = Harness(tmp_path)

    class FabricatingWriter(MockWriter):
        def write(self, *args, **kwargs):
            return (
                super()
                .write(*args, **kwargs)
                .replace("## Sources\n", "## Sources\n\n1. Fake <https://fake.example/a>\n", 1)
            )

    run_id = h.repo.create_run(DEMO)
    engine = h.engine()
    engine.agents = type(h.agents)(h.agents.planner, h.agents.analyst, FabricatingWriter())
    assert engine.run(run_id) is RunStatus.FAILED
    assert h.repo.get_summary(run_id).error.startswith(
        "write failed: Report failed evidence check: Source list URL is not a stored source"
    )
    assert h.repo.latest_report(run_id) is None
    assert h.stages(run_id)[-1] == (Stage.WRITE, StepStatus.FAILED)

    assert h.engine().resume(run_id) is RunStatus.COMPLETED  # honest writer: report saved
    assert "evidence check passed" in h.repo.list_steps(run_id)[-1].output_summary


def test_claims_expose_source_ids():
    _, claims = build()
    with_spans = next(c for c in claims if c.spans)
    expected = list(dict.fromkeys(s.source_record_id for s in with_spans.spans))
    assert with_spans.source_record_ids == expected
    assert with_spans.model_dump()["source_record_ids"] == expected


def test_escaping_blocks_autolinks_and_round_trips():
    from app.verification.markdown import md, unmd

    text = "See https://directus.io/ or www.example.com, mail me@x.io. Ratio 1:2 // ok \\. done"
    escaped = md(text)
    assert not re.search(r"[A-Za-z]://", escaped)
    assert "www." not in escaped and "e@x" not in escaped
    assert unmd(escaped) == text


def test_bare_urls_and_emails_in_body_are_rejected():
    for bare in ("https://evil.test/x", "www.evil.test", "someone@evil.test"):
        problems = problems_after(
            lambda r, b=bare: r.replace("## Findings\n", f"## Findings\n{b}\n")
        )
        assert any("link or HTML" in p for p in problems), bare

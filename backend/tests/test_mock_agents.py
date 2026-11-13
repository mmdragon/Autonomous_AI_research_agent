from datetime import UTC, datetime

from app.agents.mock import (
    MockAnalyst,
    MockPlanner,
    _keyword_pattern,
    attribute_keywords,
    entity_patterns,
    iter_sentences,
    md,
)
from app.schemas.research import ResearchRequest, SourceOut
from app.sources.models import SourceKind


def source(sid: str, kind=SourceKind.REFERENCE) -> SourceOut:
    return SourceOut(
        id=sid,
        url=f"https://x.test/{sid}",
        title=sid,
        source_name="wikipedia",
        source_kind=kind,
        retrieved_at=datetime.now(UTC),
        published_at=None,
        excerpt="",
        content_hash="h",
        license=None,
    )


def test_sentence_offsets_are_exact_and_keep_dotted_names():
    text = (
        "Strapi is built on Node.js and React. See https://strapi.io for docs!"
        "\n== History ==\nShort."
    )
    spans = list(iter_sentences(text))
    assert [text[a:b] for a, b in spans] == [
        "Strapi is built on Node.js and React.",
        "See https://strapi.io for docs!",
    ]


def test_keywords_match_whole_words_unless_prefixed():
    dev = _keyword_pattern(attribute_keywords("developer experience"))
    assert not dev.search("Notable clients include IKEA.")  # "cli" is not "clients"
    assert dev.search("It ships a CLI.")
    integrations = _keyword_pattern(attribute_keywords("integrations"))
    assert integrations.search("It integrates with Slack.")  # integrat* prefix
    pricing = _keyword_pattern(attribute_keywords("pricing"))
    assert not pricing.search("It raised $80 million in funding.")
    assert pricing.search("The free tier allows three users.")


def test_bare_product_name_matches_case_sensitively():
    patterns = entity_patterns("Sanity CMS")
    assert any(p.search("We moved to Sanity last year.") for p in patterns)
    assert not any(p.search("for the sake of sanity") for p in patterns)
    assert any(p.search("sanity cms is fine") for p in patterns)  # full name, any case


def test_planner_builds_matrix_questions_and_dedupes_queries():
    request = ResearchRequest(
        topic="Strapi",
        entities=["Strapi", "Directus"],
        attributes=["pricing"],
        questions=["Which is open source?"],
        user_urls=["https://docs.example.test/a"],
    )
    plan = MockPlanner().plan(request)
    assert [q.entity for q in plan.questions] == ["Strapi", "Directus", None]
    queries = [(q.tool, q.query) for q in plan.queries]
    assert queries.count(("wikipedia", "Strapi")) == 1  # topic and entity deduped
    assert ("user_url", "https://docs.example.test/a") in queries
    assert ("hackernews", "Which is open source?") in queries


def test_planner_without_entities_or_questions_asks_about_topic():
    plan = MockPlanner().plan(ResearchRequest(topic="vector databases"))
    assert [q.text for q in plan.questions] == ["What is vector databases?"]


def test_analyst_quotes_verbatim_with_offsets_and_records_unknowns():
    text = "Intro line here for context.\nDirectus offers REST and GraphQL APIs for SQL data."
    request = ResearchRequest(topic="cms", entities=["Directus", "Strapi"], attributes=["API"])
    plan = MockPlanner().plan(request)
    claims = MockAnalyst().analyze(request, plan, [source("s1")], {"s1": text})
    directus, strapi = claims
    span = directus.spans[0]
    assert text[span.start : span.end] == span.quote == directus.claim_text
    assert strapi.spans == [] and "No retrieved source" in strapi.claim_text


def test_analyst_prefers_reference_sources():
    contents = {
        "hn": "Directus has a great REST API, says me.",
        "wiki": "Directus provides a REST API over any SQL database.",
    }
    request = ResearchRequest(topic="cms", entities=["Directus"], attributes=["API"])
    plan = MockPlanner().plan(request)
    claims = MockAnalyst().analyze(
        request, plan, [source("hn", SourceKind.COMMUNITY), source("wiki")], contents
    )
    assert claims[0].spans[0].source_record_id == "wiki"


def test_free_question_claims_need_two_keywords():
    contents = {"s": "Strapi is open source software. Open season starts today for everyone."}
    request = ResearchRequest(topic="cms", questions=["Is Strapi open source software?"])
    claims = MockAnalyst().analyze(request, MockPlanner().plan(request), [source("s")], contents)
    assert [c.claim_text for c in claims] == ["Strapi is open source software."]


def test_markdown_escaping_neutralizes_links_html_and_tables():
    hostile = "Click [here](javascript:alert(1)) <script>x</script> | col ![img](http://t/x.png)"
    escaped = md(hostile)
    assert "[here]" not in escaped and "<script>" not in escaped
    assert "\\|" in escaped and "\\[" in escaped and "\\<" in escaped

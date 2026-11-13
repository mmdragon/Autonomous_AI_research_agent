import httpx2 as httpx
import pytest

from app.sources.fixtures import FixtureMissingError
from app.sources.http import PermanentSourceError
from app.sources.models import SourceKind
from app.sources.wikipedia import LICENSE, WikipediaSource
from tests.sources_helpers import FakeClock, make_http, mock


@pytest.fixture
def wiki() -> WikipediaSource:
    return WikipediaSource(make_http())


def test_search_normalizes_records_in_rank_order(wiki):
    records = wiki.search("headless cms", 3)
    assert [r.title for r in records] == ["Headless content management system", "Example CMS Beta"]
    first = records[0]
    assert first.url == "https://en.wikipedia.org/wiki/Headless_content_management_system"
    assert first.source_name == "wikipedia"
    assert first.source_kind is SourceKind.REFERENCE
    assert first.license == LICENSE
    assert (
        first.content == "A headless content management system is a back-end only CMS.\n\n"
        "It exposes content through an API."
    )
    assert first.retrieved_at.tzinfo is not None
    assert first.published_at is None  # Wikipedia gives no publication date; never inferred
    assert first.excerpt == first.content
    assert first.metadata["section"] == "lead"
    assert len(first.content_hash) == 64


def test_search_skips_pages_without_text(wiki):
    assert "Empty Stub" not in [r.title for r in wiki.search("headless cms", 3)]


def test_empty_query_makes_no_request():
    calls = []
    wiki = WikipediaSource(make_http(mock(lambda r: calls.append(r) or httpx.Response(500))))
    assert wiki.search("   ", 5) == []
    assert calls == []


def test_search_sends_etiquette_params_and_caps_limit():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"query": {"pages": []}})

    WikipediaSource(make_http(mock(handler))).search("x", 500)
    params = seen[0].url.params
    assert params["maxlag"] == "5"
    assert params["gsrlimit"] == "20"
    assert seen[0].url.host == "en.wikipedia.org"


def test_fetch_full_article(wiki):
    record = wiki.fetch("https://en.wikipedia.org/wiki/Example_CMS_Beta")
    assert "REST and GraphQL APIs" in record.content
    assert record.metadata == {"pageid": 2, "revision_id": 202, "section": "full"}


def test_fetch_missing_article(wiki):
    with pytest.raises(PermanentSourceError, match="not found"):
        wiki.fetch("https://en.wikipedia.org/wiki/No_Such_Page")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/wiki/Foo",
        "http://en.wikipedia.org/wiki/Foo",
        "https://en.wikipedia.org/w/index.php?title=Foo",
        "https://en.wikipedia.org/wiki/",
    ],
)
def test_fetch_rejects_non_article_urls(wiki, url):
    with pytest.raises(PermanentSourceError):
        wiki.fetch(url)


def test_maxlag_response_is_retried():
    responses = iter(
        [
            httpx.Response(
                200,
                headers={"retry-after": "3"},
                json={"error": {"code": "maxlag", "info": "lagged"}},
            ),
            httpx.Response(200, json={"query": {"pages": []}}),
        ]
    )
    clock = FakeClock()
    wiki = WikipediaSource(make_http(mock(lambda r: next(responses)), clock=clock))
    assert wiki.search("x", 1) == []
    assert clock.sleeps == [3.0]


def test_api_error_is_permanent():
    wiki = WikipediaSource(
        make_http(mock(lambda r: httpx.Response(200, json={"error": {"code": "badvalue"}})))
    )
    with pytest.raises(PermanentSourceError, match="badvalue"):
        wiki.search("x", 1)


def test_unrecorded_request_fails_clearly_offline(wiki):
    with pytest.raises(FixtureMissingError, match="offline"):
        wiki.search("something never recorded", 3)

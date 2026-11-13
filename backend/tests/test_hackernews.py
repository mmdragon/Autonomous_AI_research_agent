from datetime import UTC, datetime

import pytest

from app.sources.hackernews import HackerNewsSource
from app.sources.http import PermanentSourceError
from app.sources.models import SourceKind
from tests.sources_helpers import make_http


@pytest.fixture
def hn() -> HackerNewsSource:
    return HackerNewsSource(make_http(), max_comments=3)


def test_search_maps_hits_to_discussion_records(hn):
    records = hn.search("headless cms", 2)
    assert [r.url for r in records] == [
        "https://news.ycombinator.com/item?id=1001",
        "https://news.ycombinator.com/item?id=1002",
    ]
    show = records[0]
    assert show.source_kind is SourceKind.COMMUNITY
    assert show.published_at == datetime(2024, 3, 1, 12, tzinfo=UTC)
    assert show.metadata["points"] == 120
    assert show.metadata["linked_url"] == "https://example.com/beta"
    assert "Linked URL: https://example.com/beta" in show.content


def test_search_decodes_story_html_and_drops_usernames(hn):
    ask = hn.search("headless cms", 2)[1]
    assert 'We are a team of three & need "simple" hosting.' in ask.content
    # Random ids and hashes are hex, so only check fields that can carry source data.
    dumped = ask.model_dump_json(exclude={"id", "content_hash"})
    assert "another" not in dumped and "someone" not in dumped


def test_fetch_includes_bounded_live_comments(hn):
    record = hn.fetch("https://news.ycombinator.com/item?id=1002")
    assert record.published_at == datetime.fromtimestamp(1711929600, UTC)
    assert "Comment:\nWe use Example CMS Beta.\n\nIts GraphQL API is fine." in record.content
    assert record.metadata["comments_included"] == 2  # the deleted comment is skipped
    assert "c1" not in record.model_dump_json(exclude={"id", "content_hash"})


def test_injected_instructions_stay_inert_data(hn):
    # Source text is stored verbatim as data; nothing in the adapter acts on it.
    record = hn.fetch("https://news.ycombinator.com/item?id=1002")
    assert "Ignore previous instructions" in record.content
    assert record.source_kind is SourceKind.COMMUNITY


def test_comment_limit_is_respected():
    hn = HackerNewsSource(make_http(), max_comments=1)
    assert hn.fetch("https://news.ycombinator.com/item?id=1002").metadata["comments_included"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://news.ycombinator.com/item?id=abc",
        "https://news.ycombinator.com/user?id=1",
        "https://evil.example/item?id=1",
        "https://news.ycombinator.com/item",
    ],
)
def test_rejects_non_item_urls(url):
    with pytest.raises(PermanentSourceError):
        HackerNewsSource.item_id_from_url(url)

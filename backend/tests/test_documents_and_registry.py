import json
import os

import httpx2 as httpx
import pytest

from app.config import Settings
from app.sources.documents import load_document
from app.sources.fixtures import FixtureMissingError, RecordingTransport, ReplayTransport
from app.sources.http import BlockedError, PermanentSourceError
from app.sources.models import SearchSource, SourceKind
from app.sources.registry import build_source_tools, robots_token
from app.sources.wikipedia import WikipediaSource
from tests.sources_helpers import FIXTURES, make_http

# --- documents ---


def test_load_markdown_document():
    record = load_document(
        "../../notes/cms.md", b"# Notes\r\nStrapi is open source.", max_bytes=1000
    )
    assert record.title == "cms.md"
    assert record.url.startswith("upload://") and record.url.endswith("/cms.md")
    assert record.content == "# Notes\nStrapi is open source."
    assert record.source_kind is SourceKind.DOCUMENT


def test_same_document_gets_same_url():
    a = load_document("a.txt", b"same text", max_bytes=100)
    b = load_document("a.txt", b"same text", max_bytes=100)
    assert a.url == b.url and a.content_hash == b.content_hash


@pytest.mark.parametrize(
    "name, data, error, message",
    [
        ("x.exe", b"MZ", BlockedError, "Unsupported"),
        ("x.txt", b"x" * 101, BlockedError, "exceeds"),
        ("x.txt", b"\xff\xfe\x00bad", PermanentSourceError, "UTF-8"),
        ("x.txt", b"   \n", PermanentSourceError, "empty"),
    ],
)
def test_document_rejections(name, data, error, message):
    with pytest.raises(error, match=message):
        load_document(name, data, max_bytes=100)


# --- fixtures and registry ---


def test_replay_matches_regardless_of_param_order():
    transport = ReplayTransport(FIXTURES)
    url = "https://hn.algolia.com/api/v1/search?hitsPerPage=2&tags=story&query=headless+cms"
    response = httpx.Client(transport=transport).get(url)
    assert response.json()["nbHits"] == 3


def test_replay_missing_fixture_raises():
    with pytest.raises(FixtureMissingError):
        httpx.Client(transport=ReplayTransport(FIXTURES)).get("https://nowhere.test/")


def test_recording_round_trips_through_replay(tmp_path):
    inner = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 9,
                            "title": "Recorded",
                            "index": 1,
                            "extract": "Recorded text.",
                            "canonicalurl": "https://en.wikipedia.org/wiki/Recorded",
                        }
                    ]
                }
            },
            headers={"set-cookie": "drop-me"},
        )
    )
    WikipediaSource(make_http(RecordingTransport(tmp_path, inner))).search("rec", 1)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert "set-cookie" not in json.loads(files[0].read_text())["headers"]

    replayed = WikipediaSource(make_http(ReplayTransport(tmp_path))).search("rec", 1)
    assert [r.title for r in replayed] == ["Recorded"]


def test_live_mode_requires_configured_user_agent(tmp_path):
    settings = Settings(_env_file=None, sources_mode="live")
    with pytest.raises(ValueError, match="HTTP_USER_AGENT"):
        build_source_tools(settings)


def test_fixture_mode_builds_offline_tools():
    tools = build_source_tools(Settings(_env_file=None, fixtures_dir=FIXTURES))
    try:
        for tool in (tools.wikipedia, tools.hackernews, tools.user_url):
            assert isinstance(tool, SearchSource)
        assert tools.wikipedia.search("headless cms", 3)
        assert tools.http.rate_limiter.min_interval == 0
    finally:
        tools.close()


def test_robots_token():
    assert robots_token("research-agent-local/0.1 (x)") == "research-agent-local"


# --- opt-in live smoke test ---


@pytest.mark.skipif(not os.environ.get("RUN_LIVE_TESTS"), reason="set RUN_LIVE_TESTS=1")
def test_live_smoke():
    settings = Settings(sources_mode="live")  # reads backend/.env for HTTP_USER_AGENT
    tools = build_source_tools(settings)
    try:
        assert tools.wikipedia.search("Content management system", 2)
        assert tools.hackernews.search("headless cms", 2)
    finally:
        tools.close()

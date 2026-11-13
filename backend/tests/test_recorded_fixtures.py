"""Checks on the real responses recorded in backend/fixtures/http (offline demo data)."""

import json
import re

import pytest

from app.config import BACKEND_ROOT, Settings
from app.sources.fixtures import SCRUBBED_KEYS
from app.sources.registry import build_source_tools

RECORDED = BACKEND_ROOT / "fixtures" / "http"
FILES = sorted(RECORDED.glob("*.json"))
WIKI_QUERIES = ["headless content management system", "Strapi", "Contentful", "Sanity CMS",
                "Directus", "Payload CMS"]  # fmt: skip
HN_QUERIES = ["headless CMS", "Strapi", "Contentful", "Sanity CMS", "Directus"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

pytestmark = pytest.mark.skipif(not FILES, reason="no recorded fixtures")


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name[:50])
def test_recorded_fixture_has_no_usernames_emails_or_extra_headers(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert not SCRUBBED_KEYS & set(_keys(data.get("json")))
    assert set(data["headers"]) <= {"content-type", "retry-after", "location"}
    assert not EMAIL.search(path.read_text(encoding="utf-8"))


def test_recorded_queries_replay_offline():
    tools = build_source_tools(Settings(_env_file=None, fixtures_dir=RECORDED))
    try:
        for query in WIKI_QUERIES:
            results = tools.wikipedia.search(query, 5)
            assert results, query
            tools.wikipedia.fetch(results[0].url)
        for query in HN_QUERIES:
            results = tools.hackernews.search(query, 5)
            assert results, query
            record = tools.hackernews.fetch(results[0].url)
            assert record.published_at is not None
    finally:
        tools.close()

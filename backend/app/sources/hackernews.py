"""Hacker News adapter.

- Search: Algolia HN Search API (third-party; documented limit 10,000 requests/hour per IP).
- Fetch: official HN Firebase API, story plus a bounded number of top-level comments.

HN content is community discussion, so records are SourceKind.COMMUNITY: useful for
developer sentiment, never sufficient on its own to verify a product fact.
Usernames are not stored.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from app.sources.http import HttpClient, PermanentSourceError
from app.sources.models import SourceKind, SourceRecord
from app.sources.text import html_fragment_to_text

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
DISCUSSION_URL = "https://news.ycombinator.com/item?id={id}"
LICENSE = "Hacker News user content; attribute via discussion link"
MAX_SEARCH_LIMIT = 20


class HackerNewsSource:
    name = "hackernews"

    def __init__(self, http: HttpClient, *, max_comments: int = 5) -> None:
        self.http = http
        self.max_comments = max_comments

    def search(self, query: str, limit: int) -> list[SourceRecord]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        data = self.http.get(
            SEARCH_URL, params={"query": query, "tags": "story", "hitsPerPage": limit}
        ).json()
        hits = data.get("hits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            raise PermanentSourceError("Unexpected HN search response shape")
        records = [r for h in hits[:limit] if (r := self._search_record(h)) is not None]
        return records

    def fetch(self, url: str) -> SourceRecord:
        item_id = self.item_id_from_url(url)
        story = self._item(item_id)
        if story is None or story.get("deleted") or story.get("dead"):
            raise PermanentSourceError(f"HN item not available: {item_id}")

        parts = [story.get("title") or "", html_fragment_to_text(story.get("text"))]
        if story.get("url"):
            parts.append(f"Linked URL: {story['url']}")
        comments = 0
        for kid in (story.get("kids") or [])[: self.max_comments]:
            comment = self._item(kid)
            if not comment or comment.get("deleted") or comment.get("dead"):
                continue
            text = html_fragment_to_text(comment.get("text"))
            if text:
                parts.append(f"Comment:\n{text}")
                comments += 1

        return SourceRecord.build(
            url=DISCUSSION_URL.format(id=item_id),
            title=story.get("title") or f"HN item {item_id}",
            source_name=self.name,
            source_kind=SourceKind.COMMUNITY,
            content="\n\n".join(p for p in parts if p),
            published_at=_from_unix(story.get("time")),
            license=LICENSE,
            metadata={
                "item_id": item_id,
                "points": story.get("score"),
                "comments_included": comments,
                "linked_url": story.get("url"),
            },
        )

    @staticmethod
    def item_id_from_url(url: str) -> int:
        parsed = urlparse(url)
        ids = parse_qs(parsed.query).get("id", [])
        if parsed.hostname != "news.ycombinator.com" or parsed.path != "/item" or not ids:
            raise PermanentSourceError(f"Not a Hacker News item URL: {url}")
        if not ids[0].isdigit():
            raise PermanentSourceError(f"Invalid Hacker News item id in: {url}")
        return int(ids[0])

    def _item(self, item_id: int) -> dict | None:
        data = self.http.get(ITEM_URL.format(id=int(item_id))).json()
        return data if isinstance(data, dict) else None

    def _search_record(self, hit: dict) -> SourceRecord | None:
        item_id = str(hit.get("objectID", ""))
        title = hit.get("title")
        if not item_id.isdigit() or not title:
            return None
        parts = [title, html_fragment_to_text(hit.get("story_text"))]
        if hit.get("url"):
            parts.append(f"Linked URL: {hit['url']}")
        return SourceRecord.build(
            url=DISCUSSION_URL.format(id=item_id),
            title=title,
            source_name=self.name,
            source_kind=SourceKind.COMMUNITY,
            content="\n\n".join(p for p in parts if p),
            published_at=_parse_iso(hit.get("created_at")),
            license=LICENSE,
            metadata={
                "item_id": int(item_id),
                "points": hit.get("points"),
                "num_comments": hit.get("num_comments"),
                "linked_url": hit.get("url"),
            },
        )


def _from_unix(value: object) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int) else None


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

"""Normalized source records shared by every adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

from app.sources.text import content_hash, make_excerpt, normalize_text


class SourceKind(StrEnum):
    REFERENCE = "reference"  # encyclopedic reference (Wikipedia)
    COMMUNITY = "community"  # user discussion; opinion, not verified fact (Hacker News)
    USER_URL = "user_url"  # a page the user asked us to read
    DOCUMENT = "document"  # a file the user uploaded


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceRecord(BaseModel):
    """One retrieved source. `content` is exactly the normalized text that was fetched.

    The repository stores `content` in `source_contents`; evidence quotes are later checked
    against it, so adapters must never alter it after hashing.
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    url: str
    title: str
    source_name: str
    source_kind: SourceKind
    retrieved_at: datetime
    published_at: datetime | None = None  # only when the source states it; never inferred
    excerpt: str
    content: str
    content_hash: str
    license: str | None = None
    # Adapter-specific facts worth showing (e.g. HN points). No personal data.
    metadata: dict[str, str | int | None] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        url: str,
        title: str,
        source_name: str,
        source_kind: SourceKind,
        content: str,
        retrieved_at: datetime | None = None,
        published_at: datetime | None = None,
        license: str | None = None,
        metadata: dict[str, str | int | None] | None = None,
        excerpt_chars: int = 500,
    ) -> SourceRecord:
        text = normalize_text(content)
        return cls(
            url=url,
            title=normalize_text(title) or url,
            source_name=source_name,
            source_kind=source_kind,
            retrieved_at=retrieved_at or utc_now(),
            published_at=published_at,
            excerpt=make_excerpt(text, excerpt_chars),
            content=text,
            content_hash=content_hash(text),
            license=license,
            metadata=metadata or {},
        )


@runtime_checkable
class SearchSource(Protocol):
    """A replaceable source tool. All methods are read-only."""

    name: str

    def search(self, query: str, limit: int) -> list[SourceRecord]: ...

    def fetch(self, url: str) -> SourceRecord: ...

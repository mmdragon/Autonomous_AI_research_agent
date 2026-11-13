"""Builds the source tools for the configured mode."""

from __future__ import annotations

from dataclasses import dataclass

import httpx2 as httpx

from app.config import Settings
from app.sources.fixtures import ReplayTransport
from app.sources.hackernews import HackerNewsSource
from app.sources.http import HttpClient
from app.sources.user_url import UserUrlSource, system_resolver
from app.sources.wikipedia import WikipediaSource

UNCONFIGURED_AGENT_MARKER = "contact not configured"


@dataclass
class SourceTools:
    http: HttpClient
    wikipedia: WikipediaSource
    hackernews: HackerNewsSource
    user_url: UserUrlSource

    def close(self) -> None:
        self.http.close()


def robots_token(user_agent: str) -> str:
    """The product token robots.txt rules match on, e.g. 'research-agent-local'."""
    return user_agent.split("/", 1)[0].split(" ", 1)[0] or "*"


def build_source_tools(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> SourceTools:
    offline = settings.sources_mode == "fixtures"
    if not offline and UNCONFIGURED_AGENT_MARKER in settings.http_user_agent:
        raise ValueError(
            "Set HTTP_USER_AGENT with your own contact in backend/.env before SOURCES_MODE=live "
            "(Wikimedia API etiquette)."
        )
    if transport is None and offline:
        transport = ReplayTransport(settings.fixtures_dir)
    http = HttpClient(
        user_agent=settings.http_user_agent,
        timeout=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        min_interval=0.0 if offline else settings.http_min_interval_seconds,
        max_bytes=settings.max_fetch_bytes,
        transport=transport,
    )
    return SourceTools(
        http=http,
        wikipedia=WikipediaSource(http),
        hackernews=HackerNewsSource(http),
        user_url=UserUrlSource(
            http,
            robots_user_agent=robots_token(settings.http_user_agent),
            # Offline mode never opens a connection, so hostnames are not resolved there.
            resolver=None if offline else system_resolver,
        ),
    )

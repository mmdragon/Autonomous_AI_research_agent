"""Record live API responses as offline fixtures.

Usage (makes real, rate-limited requests to Wikipedia and Hacker News):
    uv run python -m scripts.record_fixtures "headless CMS" "Strapi" --hn "headless CMS"

Requires HTTP_USER_AGENT with your own contact in backend/.env.
Recorded files go to backend/fixtures/http/ and are replayed when SOURCES_MODE=fixtures.
"""

from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.sources.fixtures import RecordingTransport
from app.sources.http import SourceError
from app.sources.registry import build_source_tools


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wikipedia_queries", nargs="*", help="Wikipedia search queries")
    parser.add_argument("--hn", action="append", default=[], help="Hacker News search query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--fetch-top", type=int, default=1, help="full fetches per query")
    args = parser.parse_args()

    settings = get_settings().model_copy(update={"sources_mode": "live"})
    transport = RecordingTransport(settings.fixtures_dir)
    try:
        tools = build_source_tools(settings, transport=transport)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        for source, queries in (
            (tools.wikipedia, args.wikipedia_queries),
            (tools.hackernews, args.hn),
        ):
            for query in queries:
                records = source.search(query, args.limit)
                print(f"{source.name}: {query!r} -> {len(records)} results")
                for record in records[: args.fetch_top]:
                    source.fetch(record.url)
                    print(f"  fetched {record.url}")
    except SourceError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        tools.close()
    print(f"Fixtures written to {settings.fixtures_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline replay of recorded HTTP responses (SOURCES_MODE=fixtures).

Each fixture is one JSON file:
    {"request_url": "...", "status": 200, "headers": {...}, "json": ... | "text": "..."}
Requests are matched on the canonical URL (query parameters sorted), so the file name is free.
Fixtures recorded from live APIs keep their real content; never hand-edit recorded content.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx2 as httpx

from app.sources.http import PermanentSourceError

# Usernames are personal data we never store; they are removed before a fixture is written.
SCRUBBED_KEYS = frozenset({"author", "by"})


class FixtureMissingError(PermanentSourceError):
    pass


def scrub(value: object) -> object:
    """Recursively drop username fields (HN `by`, Algolia `author` incl. highlight results)."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in SCRUBBED_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def canonical_url(url: httpx.URL | str) -> str:
    url = httpx.URL(str(url))
    query = "&".join(f"{k}={v}" for k, v in sorted(url.params.multi_items()))
    base = f"{url.scheme}://{url.host}{url.path}"
    return f"{base}?{query}" if query else base


def _response_from_fixture(data: dict, request: httpx.Request) -> httpx.Response:
    headers = dict(data.get("headers") or {})
    if "json" in data:
        body = json.dumps(data["json"]).encode()
        headers.setdefault("content-type", "application/json")
    else:
        body = str(data.get("text", "")).encode()
    return httpx.Response(data.get("status", 200), headers=headers, content=body, request=request)


class ReplayTransport(httpx.BaseTransport):
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures: dict[str, dict] = {}
        if fixtures_dir.is_dir():
            for path in sorted(fixtures_dir.rglob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.fixtures[canonical_url(data["request_url"])] = data

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = canonical_url(request.url)
        data = self.fixtures.get(key)
        if data is None:
            raise FixtureMissingError(f"No recorded fixture for {key} (offline mode)")
        return _response_from_fixture(data, request)


class RecordingTransport(httpx.BaseTransport):
    """Passes requests to a real transport and writes each response as a fixture file."""

    def __init__(self, out_dir: Path, inner: httpx.BaseTransport | None = None) -> None:
        self.out_dir = out_dir
        self.inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        body = response.read()
        key = canonical_url(request.url)
        content_type = response.headers.get("content-type", "")
        fixture: dict = {
            "request_url": key,
            "status": response.status_code,
            "headers": {
                k: v
                for k, v in response.headers.items()
                if k.lower() in {"content-type", "retry-after", "location"}
            },
        }
        if "json" in content_type:
            fixture["json"] = scrub(json.loads(body))
            body = json.dumps(fixture["json"]).encode()  # caller sees what replay will serve
        else:
            fixture["text"] = body.decode(response.encoding or "utf-8", errors="replace")
        # Readable prefix plus a hash of the full key, so long URLs never collide.
        readable = re.sub(r"[^a-z0-9]+", "-", key.lower().split("://", 1)[-1])[:80].strip("-")
        slug = f"{readable}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"{slug}.json").write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in {"content-length", "content-encoding"}
        }
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)

    def close(self) -> None:
        self.inner.close()

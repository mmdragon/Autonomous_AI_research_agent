"""Shared HTTP client for source adapters: timeouts, per-host rate limiting, bounded retries.

Only GET is supported: every source tool is read-only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

import httpx2 as httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 30.0


class SourceError(Exception):
    """Base class for source failures. `message` is safe to show and store."""


class TransientSourceError(SourceError):
    """Timeouts, connection errors, 429 and 5xx after retries were exhausted."""


class PermanentSourceError(SourceError):
    """A request that will not succeed if repeated (4xx, malformed response)."""


class BlockedError(SourceError):
    """A request refused by our own policy: robots.txt, private address, type or size limit."""


@dataclass
class FetchedResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    attempts: int

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def charset(self) -> str:
        for part in self.headers.get("content-type", "").split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                return value.strip("\"'")
        return "utf-8"

    def text(self) -> str:
        try:
            return self.body.decode(self.charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError as exc:
            raise PermanentSourceError(f"Invalid JSON from {self.url}") from exc


@dataclass
class RateLimiter:
    """Enforces a minimum interval between requests to the same host."""

    min_interval: float
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: dict[str, float] = field(default_factory=dict)

    def wait(self, host: str) -> None:
        if self.min_interval <= 0:
            return
        last = self._last.get(host)
        if last is not None:
            remaining = self.min_interval - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last[host] = self.clock()


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        min_interval: float = 1.0,
        max_bytes: int = 2 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_bytes = max_bytes
        self.sleep = sleep
        self.request_count = 0  # every HTTP request sent, including retries
        self.rate_limiter = RateLimiter(min_interval, clock=clock, sleep=sleep)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,  # callers that allow redirects re-validate each hop
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
        retry_after_for: Callable[[FetchedResponse], float | None] | None = None,
    ) -> FetchedResponse:
        """GET with bounded retries on transient failures.

        `retry_after_for` lets an adapter mark a 200 response as transient (e.g. Wikimedia
        `maxlag`) by returning a delay in seconds; None means the response is final.
        Redirect responses (3xx) are returned as-is.
        """
        limit = max_bytes or self.max_bytes
        attempts = 0
        last_error = "request failed"
        while True:
            attempts += 1
            delay: float | None = None
            try:
                response = self._send(url, params, headers, limit, attempts)
            except httpx.TimeoutException:
                last_error = f"Timed out fetching {url}"
            except httpx.TransportError as exc:
                last_error = f"Connection error fetching {url}: {type(exc).__name__}"
            else:
                status = response.status_code
                if status in RETRYABLE_STATUS:
                    last_error = f"HTTP {status} from {url}"
                    delay = parse_retry_after(response.headers.get("retry-after"))
                elif 400 <= status < 500:
                    raise PermanentSourceError(f"HTTP {status} from {url}")
                elif retry_after_for and (adapter_delay := retry_after_for(response)) is not None:
                    last_error = f"Server asked to retry later: {url}"
                    delay = adapter_delay
                else:
                    return response

            if attempts > self.max_retries:
                raise TransientSourceError(f"{last_error} (after {attempts} attempts)")
            backoff = self.backoff_base * 2 ** (attempts - 1)
            self.sleep(min(max(backoff, delay or 0.0), MAX_RETRY_AFTER_SECONDS))

    def _send(
        self,
        url: str,
        params: Mapping[str, str | int] | None,
        headers: Mapping[str, str] | None,
        limit: int,
        attempts: int,
    ) -> FetchedResponse:
        request = self._client.build_request("GET", url, params=params, headers=headers)
        self.rate_limiter.wait(request.url.host)
        self.request_count += 1
        response = self._client.send(request, stream=True)
        try:
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise BlockedError(f"Response from {url} exceeds {limit} bytes")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise BlockedError(f"Response from {url} exceeds {limit} bytes")
                chunks.append(chunk)
        finally:
            response.close()
        return FetchedResponse(
            url=str(request.url),
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=b"".join(chunks),
            attempts=attempts,
        )

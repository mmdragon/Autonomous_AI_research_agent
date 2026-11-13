import httpx2 as httpx
import pytest

from app.sources.http import (
    BlockedError,
    PermanentSourceError,
    RateLimiter,
    TransientSourceError,
    parse_retry_after,
)
from tests.sources_helpers import TEST_AGENT, FakeClock, make_http, mock

URL = "https://api.example.test/data"


def sequence(*responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, calls


def test_retries_transient_status_then_succeeds_with_backoff():
    handler, calls = sequence(httpx.Response(503), httpx.Response(502), httpx.Response(200))
    clock = FakeClock()
    response = make_http(mock(handler), clock=clock).get(URL)
    assert response.status_code == 200
    assert response.attempts == 3
    assert clock.sleeps == [1.0, 2.0]
    assert calls[0].headers["user-agent"] == TEST_AGENT


def test_retry_after_header_is_honored_and_capped():
    handler, _ = sequence(httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200))
    clock = FakeClock()
    make_http(mock(handler), clock=clock).get(URL)
    assert clock.sleeps == [7.0]
    assert parse_retry_after("9999") == 30.0
    assert parse_retry_after("soon") is None


def test_gives_up_after_bounded_attempts():
    handler, calls = sequence(httpx.ConnectTimeout("slow"))
    with pytest.raises(TransientSourceError, match="after 3 attempts"):
        make_http(mock(handler), max_retries=2).get(URL)
    assert len(calls) == 3


def test_connection_error_is_transient():
    handler, calls = sequence(httpx.ConnectError("refused"), httpx.Response(200))
    assert make_http(mock(handler)).get(URL).status_code == 200
    assert len(calls) == 2


def test_client_errors_are_not_retried():
    handler, calls = sequence(httpx.Response(404))
    with pytest.raises(PermanentSourceError, match="HTTP 404"):
        make_http(mock(handler)).get(URL)
    assert len(calls) == 1


def test_adapter_hook_can_mark_200_as_transient():
    handler, calls = sequence(httpx.Response(200, json={"lag": True}), httpx.Response(200))
    hook_calls = []

    def hook(response):
        hook_calls.append(response)
        return 5.0 if len(hook_calls) == 1 else None

    clock = FakeClock()
    make_http(mock(handler), clock=clock).get(URL, retry_after_for=hook)
    assert len(calls) == 2
    assert clock.sleeps == [5.0]


def test_body_over_limit_is_blocked():
    handler, _ = sequence(httpx.Response(200, content=b"x" * 2000))
    with pytest.raises(BlockedError, match="exceeds"):
        make_http(mock(handler), max_bytes=1000).get(URL)


def test_declared_length_over_limit_is_blocked():
    handler, _ = sequence(httpx.Response(200, headers={"content-length": "5000"}, content=b"x"))
    with pytest.raises(BlockedError):
        make_http(mock(handler), max_bytes=1000).get(URL)


def test_rate_limiter_spaces_requests_per_host():
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    limiter.wait("a.test")
    clock.now += 0.25
    limiter.wait("a.test")
    limiter.wait("b.test")
    assert clock.sleeps == [0.75]


def test_client_applies_rate_limit():
    handler, _ = sequence(httpx.Response(200))
    clock = FakeClock()
    http = make_http(mock(handler), clock=clock, min_interval=1.0)
    http.get(URL)
    http.get(URL)
    assert clock.sleeps == [1.0]


def test_charset_and_json_helpers():
    handler, _ = sequence(
        httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=latin-1"},
            content="café".encode("latin-1"),
        )
    )
    response = make_http(mock(handler)).get(URL)
    assert response.content_type == "text/plain"
    assert response.text() == "café"
    with pytest.raises(PermanentSourceError, match="Invalid JSON"):
        response.json()

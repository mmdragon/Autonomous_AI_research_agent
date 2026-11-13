from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx2 as httpx

from app.sources.fixtures import ReplayTransport
from app.sources.http import HttpClient

FIXTURES = Path(__file__).parent / "fixtures" / "http"
TEST_AGENT = "research-agent-test/0.1 (tests)"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_http(
    transport: httpx.BaseTransport | None = None,
    *,
    clock: FakeClock | None = None,
    max_retries: int = 3,
    min_interval: float = 0.0,
    max_bytes: int = 100_000,
) -> HttpClient:
    clock = clock or FakeClock()
    return HttpClient(
        user_agent=TEST_AGENT,
        max_retries=max_retries,
        min_interval=min_interval,
        max_bytes=max_bytes,
        transport=transport or ReplayTransport(FIXTURES),
        sleep=clock.sleep,
        clock=clock,
    )


def mock(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)

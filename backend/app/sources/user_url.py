"""Fetch a single page the user explicitly provided.

The workflow must only pass URLs typed by the user; this adapter never discovers URLs.
Guards:
- http/https only, no credentials in the URL, ports 80/443 only;
- every resolved address must be public (blocks loopback, private, link-local, metadata IPs);
- robots.txt is honored (RFC 9309: 4xx means allowed, 5xx/unreachable means disallowed);
- at most 3 redirects, each hop re-validated;
- text/html, text/plain and text/markdown only, size-capped by the HttpClient.

Known limit: DNS is resolved for validation and again by the HTTP client, so a hostile DNS
server could rebind between the two. Acceptable for a local, user-driven tool.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from app.sources.http import (
    BlockedError,
    FetchedResponse,
    HttpClient,
    PermanentSourceError,
    TransientSourceError,
)
from app.sources.models import SourceKind, SourceRecord
from app.sources.text import html_to_text

ALLOWED_TYPES = {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}
ALLOWED_PORTS = {None, 80, 443}
REDIRECT_STATUS = {301, 302, 303, 307, 308}

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise PermanentSourceError(f"Could not resolve host: {host}") from exc
    return sorted({info[4][0] for info in infos})


class UserUrlSource:
    name = "user_url"

    def __init__(
        self,
        http: HttpClient,
        *,
        robots_user_agent: str,
        resolver: Resolver | None = system_resolver,
        max_redirects: int = 3,
    ) -> None:
        self.http = http
        self.robots_user_agent = robots_user_agent
        self.resolver = resolver
        self.max_redirects = max_redirects
        self._robots: dict[str, RobotFileParser | None] = {}

    def search(self, query: str, limit: int) -> list[SourceRecord]:
        return []  # user URLs are fetched directly, never searched

    def fetch(self, url: str) -> SourceRecord:
        current = url.strip()
        for _ in range(self.max_redirects + 1):
            self.validate(current)
            self._check_robots(current)
            response = self.http.get(current)
            if response.status_code in REDIRECT_STATUS:
                location = response.headers.get("location")
                if not location:
                    raise PermanentSourceError(f"Redirect without location from {current}")
                current = urljoin(current, location)
                continue
            return self._record(current, response)
        raise BlockedError(f"Too many redirects starting from {url}")

    def validate(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise BlockedError(f"Only http and https URLs are allowed: {url}")
        if not parsed.hostname:
            raise BlockedError(f"URL has no host: {url}")
        if parsed.username or parsed.password:
            raise BlockedError("URLs with embedded credentials are not allowed")
        try:
            port = parsed.port
        except ValueError as exc:
            raise BlockedError(f"Invalid port in URL: {url}") from exc
        if port not in ALLOWED_PORTS:
            raise BlockedError(f"Only ports 80 and 443 are allowed: {url}")

        host = parsed.hostname
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
                raise BlockedError(f"Local hostnames are not allowed: {host}") from None
            if self.resolver is None:  # offline replay: no connection is ever made
                return
            addresses = self.resolver(host)
        if not addresses:
            raise PermanentSourceError(f"Could not resolve host: {host}")
        for address in addresses:
            ip = ipaddress.ip_address(address.split("%")[0])
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if not ip.is_global or ip.is_multicast:
                raise BlockedError(f"{host} resolves to a non-public address")

    def _check_robots(self, url: str) -> None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        if parser is None:
            raise BlockedError(f"robots.txt for {origin} could not be read; not fetching")
        if not parser.can_fetch(self.robots_user_agent, url):
            raise BlockedError(f"robots.txt disallows fetching {url}")

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            response = self.http.get(f"{origin}/robots.txt", max_bytes=512 * 1024)
        except PermanentSourceError:  # 4xx: no usable robots.txt, all paths allowed
            parser.parse([])
            return parser
        except (TransientSourceError, BlockedError):
            return None
        if response.status_code in REDIRECT_STATUS:
            parser.parse([])  # redirected robots.txt: treated as absent (not followed)
            return parser
        parser.parse(response.text().splitlines())
        return parser

    def _record(self, url: str, response: FetchedResponse) -> SourceRecord:
        if response.status_code != 200:
            raise PermanentSourceError(f"HTTP {response.status_code} from {url}")
        content_type = response.content_type
        if content_type not in ALLOWED_TYPES:
            raise BlockedError(f"Unsupported content type {content_type or 'unknown'}: {url}")
        if content_type in {"text/html", "application/xhtml+xml"}:
            text, title = html_to_text(response.text())
        else:
            text, title = response.text(), None
        if not text.strip():
            raise PermanentSourceError(f"No readable text at {url}")
        return SourceRecord.build(
            url=url,
            title=title or urlparse(url).netloc,
            source_name=self.name,
            source_kind=SourceKind.USER_URL,
            content=text,
            metadata={"content_type": content_type},
        )

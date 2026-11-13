"""Wikipedia adapter (MediaWiki Action API).

Etiquette followed (https://www.mediawiki.org/wiki/API:Etiquette):
- descriptive User-Agent with contact (set by the shared HttpClient),
- serial requests with a per-host minimum interval,
- `maxlag` on every request, backing off when the server reports lag.
Content is CC BY-SA 4.0; records carry the license and the article URL for attribution.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from app.sources.http import FetchedResponse, HttpClient, PermanentSourceError
from app.sources.models import SourceKind, SourceRecord

LICENSE = "CC BY-SA 4.0 (Wikipedia contributors)"
MAX_SEARCH_LIMIT = 20
MAXLAG_SECONDS = 5


def _maxlag_delay(response: FetchedResponse) -> float | None:
    if response.content_type != "application/json":
        return None
    error = response.json().get("error") or {}
    if error.get("code") == "maxlag":
        retry_after = response.headers.get("retry-after", str(MAXLAG_SECONDS))
        return float(retry_after) if retry_after.isdigit() else float(MAXLAG_SECONDS)
    return None


class WikipediaSource:
    name = "wikipedia"

    def __init__(self, http: HttpClient, *, language: str = "en") -> None:
        self.http = http
        self.host = f"{language}.wikipedia.org"
        self.api_url = f"https://{self.host}/w/api.php"

    def _query(self, params: dict[str, str | int]) -> dict:
        response = self.http.get(
            self.api_url,
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "maxlag": MAXLAG_SECONDS,
                **params,
            },
            retry_after_for=_maxlag_delay,
        )
        data = response.json()
        if not isinstance(data, dict):
            raise PermanentSourceError("Unexpected Wikipedia response shape")
        if error := data.get("error"):
            raise PermanentSourceError(f"Wikipedia API error: {error.get('code', 'unknown')}")
        return data

    def search(self, query: str, limit: int) -> list[SourceRecord]:
        """Search articles; each record holds the article's lead section as plain text."""
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        data = self._query(
            {
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": limit,
                "gsrnamespace": 0,
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "exlimit": "max",
                "inprop": "url",
                "redirects": 1,
            }
        )
        pages = data.get("query", {}).get("pages", [])
        pages = sorted(pages, key=lambda p: p.get("index", 0))
        return [r for p in pages if (r := self._record(p, section="lead")) is not None]

    def fetch(self, url: str) -> SourceRecord:
        """Fetch the full plain-text extract of one article by its wikipedia.org URL."""
        title = self.title_from_url(url)
        data = self._query(
            {
                "titles": title,
                "prop": "extracts|info",
                "explaintext": 1,
                "inprop": "url",
                "redirects": 1,
            }
        )
        pages = data.get("query", {}).get("pages", [])
        record = self._record(pages[0], section="full") if pages else None
        if record is None:
            raise PermanentSourceError(f"Wikipedia article not found: {title}")
        return record

    def title_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != self.host:
            raise PermanentSourceError(f"Not a {self.host} article URL: {url}")
        if not parsed.path.startswith("/wiki/") or len(parsed.path) <= len("/wiki/"):
            raise PermanentSourceError(f"Not a Wikipedia article URL: {url}")
        return unquote(parsed.path.removeprefix("/wiki/")).replace("_", " ")

    def _record(self, page: dict, *, section: str) -> SourceRecord | None:
        if page.get("missing") or page.get("invalid") or not page.get("extract"):
            return None
        return SourceRecord.build(
            url=page.get("canonicalurl") or page.get("fullurl") or "",
            title=page["title"],
            source_name=self.name,
            source_kind=SourceKind.REFERENCE,
            content=page["extract"],
            license=LICENSE,
            metadata={
                "pageid": page.get("pageid"),
                "revision_id": page.get("lastrevid"),
                "section": section,
            },
        )

import httpx2 as httpx
import pytest

from app.sources.http import BlockedError, PermanentSourceError
from app.sources.models import SourceKind
from app.sources.user_url import UserUrlSource
from tests.sources_helpers import make_http, mock

PUBLIC = {"docs.example.test": ["93.184.215.14"], "cdn.example.test": ["2606:4700::1"]}


def resolver(host):
    return PUBLIC.get(host, ["10.0.0.5"])


def site(pages, robots=(200, "")):
    """pages: path -> httpx.Response. robots: (status, body)."""
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(robots[0], text=robots[1])
        return pages.get(request.url.path, httpx.Response(404))

    return handler, requests


def source(handler):
    return UserUrlSource(
        make_http(mock(handler)), robots_user_agent="research-agent-test", resolver=resolver
    )


HTML = httpx.Response(
    200,
    headers={"content-type": "text/html; charset=utf-8"},
    text="<title>Pricing</title><p>Starter plan: $10 per month.</p><script>x()</script>",
)


def test_fetches_html_and_records_metadata():
    handler, _ = site({"/pricing": HTML})
    record = source(handler).fetch("https://docs.example.test/pricing")
    assert record.title == "Pricing"
    assert record.content == "Starter plan: $10 per month."
    assert record.source_kind is SourceKind.USER_URL
    assert record.metadata == {"content_type": "text/html"}


@pytest.mark.parametrize(
    "url, message",
    [
        ("ftp://docs.example.test/x", "http and https"),
        ("file:///etc/passwd", "http and https"),
        ("https://user:pw@docs.example.test/", "credentials"),
        ("https://docs.example.test:8080/", "ports"),
        ("http://localhost/admin", "Local hostnames"),
        ("http://127.0.0.1/", "non-public"),
        ("http://169.254.169.254/latest/meta-data", "non-public"),
        ("http://[::1]/", "non-public"),
        ("http://[::ffff:10.0.0.1]/", "non-public"),
        ("https://internal.example.test/", "non-public"),  # resolves to 10.0.0.5
    ],
)
def test_blocks_unsafe_urls_before_any_request(url, message):
    handler, requests = site({})
    with pytest.raises(BlockedError, match=message):
        source(handler).fetch(url)
    assert requests == []


def test_robots_disallow_is_honored():
    handler, requests = site(
        {"/private/a": HTML}, robots=(200, "User-agent: *\nDisallow: /private/")
    )
    with pytest.raises(BlockedError, match="robots.txt disallows"):
        source(handler).fetch("https://docs.example.test/private/a")
    assert requests == ["https://docs.example.test/robots.txt"]


def test_robots_404_allows_and_is_cached():
    handler, requests = site({"/pricing": HTML, "/other": HTML}, robots=(404, ""))
    src = source(handler)
    src.fetch("https://docs.example.test/pricing")
    src.fetch("https://docs.example.test/other")
    assert requests.count("https://docs.example.test/robots.txt") == 1


def test_robots_server_error_blocks():
    handler, _ = site({"/pricing": HTML}, robots=(503, ""))
    src = UserUrlSource(
        make_http(mock(handler), max_retries=0),
        robots_user_agent="research-agent-test",
        resolver=resolver,
    )
    with pytest.raises(BlockedError, match="could not be read"):
        src.fetch("https://docs.example.test/pricing")


def test_redirect_to_private_host_is_blocked():
    handler, requests = site(
        {"/go": httpx.Response(302, headers={"location": "http://internal.example.test/x"})}
    )
    with pytest.raises(BlockedError, match="non-public"):
        source(handler).fetch("https://docs.example.test/go")
    assert "internal.example.test" not in " ".join(requests)


def test_redirect_is_followed_and_final_url_recorded():
    handler, _ = site(
        {"/old": httpx.Response(301, headers={"location": "/pricing"}), "/pricing": HTML}
    )
    record = source(handler).fetch("https://docs.example.test/old")
    assert record.url == "https://docs.example.test/pricing"


def test_redirect_loop_is_bounded():
    handler, _ = site({"/loop": httpx.Response(302, headers={"location": "/loop"})})
    with pytest.raises(BlockedError, match="Too many redirects"):
        source(handler).fetch("https://docs.example.test/loop")


def test_rejects_unsupported_content_type():
    handler, _ = site(
        {"/file.zip": httpx.Response(200, headers={"content-type": "application/zip"})}
    )
    with pytest.raises(BlockedError, match="content type"):
        source(handler).fetch("https://docs.example.test/file.zip")


def test_empty_page_is_an_error():
    handler, _ = site(
        {
            "/blank": httpx.Response(
                200, headers={"content-type": "text/html"}, text="<script>only()</script>"
            )
        }
    )
    with pytest.raises(PermanentSourceError, match="No readable text"):
        source(handler).fetch("https://docs.example.test/blank")


def test_search_is_not_supported():
    handler, requests = site({})
    assert source(handler).search("anything", 5) == []
    assert requests == []


def test_offline_mode_skips_dns_but_still_blocks_literal_ips():
    handler, _ = site({"/pricing": HTML})
    src = UserUrlSource(make_http(mock(handler)), robots_user_agent="t", resolver=None)
    assert src.fetch("https://docs.example.test/pricing").title == "Pricing"
    with pytest.raises(BlockedError):
        src.fetch("http://192.168.1.1/")

from app.sources.text import (
    content_hash,
    html_fragment_to_text,
    html_to_text,
    make_excerpt,
    normalize_text,
)


def test_normalize_collapses_spaces_keeps_paragraphs():
    raw = "  Hello \t world \r\n\r\n\r\n\nNext\x00 para  "
    assert normalize_text(raw) == "Hello world\n\nNext para"


def test_excerpt_is_prefix_cut_on_word_boundary():
    text = "word " * 200
    excerpt = make_excerpt(text.strip(), 50)
    assert excerpt.endswith("…")
    assert text.startswith(excerpt.removesuffix("…"))
    assert len(excerpt) <= 51
    assert make_excerpt("short", 50) == "short"


def test_hash_is_stable_and_content_sensitive():
    assert content_hash("a") == content_hash("a")
    assert content_hash("a") != content_hash("b")


def test_html_to_text_drops_scripts_and_reads_title():
    html = """<html><head><title> My  Page </title><style>p{}</style></head>
    <body><script>alert('x')</script><h1>Heading</h1><p>First &amp; second.</p>
    <form><input value="secret"></form><p>Last</p></body></html>"""
    text, title = html_to_text(html)
    assert title == "My Page"
    assert "alert" not in text and "secret" not in text
    assert text == "Heading\n\nFirst & second.\n\nLast"


def test_html_fragment_keeps_literal_angle_brackets_as_text():
    assert html_fragment_to_text("a &lt;b&gt; c<p>d") == "a <b> c\n\nd"
    assert html_fragment_to_text(None) == ""

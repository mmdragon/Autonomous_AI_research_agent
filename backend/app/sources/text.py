"""Text normalization helpers. Retrieved text is data; nothing here interprets it."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from html.parser import HTMLParser

_WS_RUN = re.compile(r"[ \t\f\v ]+")
_BLANK_LINES = re.compile(r"\n{3,}")
# Control characters other than newline and tab are dropped.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def normalize_text(text: str) -> str:
    """NFC-normalize, strip control chars, collapse spaces, keep paragraph breaks."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    lines = [_WS_RUN.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def content_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def make_excerpt(text: str, max_chars: int = 500) -> str:
    """First `max_chars` of text, cut at a word boundary. Always a prefix of `text`."""
    if len(text) <= max_chars:
        return text
    cut = text.rfind(" ", 0, max_chars)
    return text[: cut if cut > max_chars // 2 else max_chars].rstrip() + "…"


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe", "form"}
    _BLOCK = {
        "p", "div", "li", "ul", "ol", "tr", "table", "section", "article",
        "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote",
    }  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str | None]:
    """Return (visible text, <title>) from HTML. Scripts, styles and forms are dropped."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    title = normalize_text(parser.title) if parser.title else None
    return normalize_text(text), title


def html_fragment_to_text(fragment: str | None) -> str:
    """Hacker News `text` fields are small HTML fragments (<p>, <a>, <i>, entities)."""
    if not fragment:
        return ""
    return html_to_text(fragment)[0]

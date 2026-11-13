"""Escaping for source text placed in reports, and its exact inverse for the report check."""

from __future__ import annotations

import re

# Enough to stop links, images, HTML, emphasis and table breaks in quoted source text.
# Curly quotes are escaped too, so a quote's boundaries in the report are unambiguous.
# "@" is escaped so GFM can't autolink email addresses.
_SPECIAL = re.compile(r"([\\`*_\[\]<>|~“”@])")
# GFM also autolinks bare "http://", "https://" and "www." text; escaping the ":" or "."
# breaks the pattern while rendering the same characters.
_SCHEME = re.compile(r"(?<=[A-Za-z]):(?=//)")
_WWW = re.compile(r"(?<![\w.])(www)\.(?=\w)", re.IGNORECASE)
_ESCAPED = re.compile(r"\\([\\`*_\[\]<>|~“”@:.])")


def md(text: str) -> str:
    """Collapse whitespace and escape Markdown so source text renders literally."""
    escaped = _SPECIAL.sub(r"\\\1", " ".join(text.split()))
    return _WWW.sub(r"\1\\.", _SCHEME.sub(r"\\:", escaped))


def unmd(text: str) -> str:
    """Inverse of md() (up to whitespace collapsing)."""
    return _ESCAPED.sub(r"\1", text)


def squash(text: str) -> str:
    return " ".join(text.split())

"""Sentence and entity matching shared by the analyst and the conflict detector."""

from __future__ import annotations

import re
from collections.abc import Iterator

MAX_SENTENCE_CHARS = 400
MIN_SENTENCE_CHARS = 20

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def iter_sentences(text: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) offsets of sentence-like spans, trimmed of whitespace.

    A sentence ends at . ! or ? followed by whitespace, or at a line break, so "Node.js"
    and URLs stay intact. Abbreviations like "Inc." still split; acceptable for a mock.
    """
    pos = 0
    for brk in [*_SENTENCE_BREAK.finditer(text), None]:
        start, end = pos, (brk.start() if brk else len(text))
        pos = brk.end() if brk else len(text)
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        segment = text[start:end]
        if segment.startswith("=") or not (
            MIN_SENTENCE_CHARS <= len(segment) <= MAX_SENTENCE_CHARS
        ):
            continue  # Wikipedia section headings, fragments, run-ons
        yield start, end


def entity_patterns(entity: str) -> list[re.Pattern[str]]:
    patterns = [re.compile(rf"(?<!\w){re.escape(entity)}(?!\w)", re.IGNORECASE)]
    short = re.sub(r"\s+(cms|headless cms)$", "", entity, flags=re.IGNORECASE)
    if short != entity and len(short) >= 3:
        # The bare product name must match case-sensitively ("Sanity", not "sanity").
        patterns.append(re.compile(rf"(?<!\w){re.escape(short)}(?!\w)"))
    return patterns

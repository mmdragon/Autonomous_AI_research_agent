"""Final evidence check on a generated report, run before it is saved.

The writer can be swapped (mock today, possibly an LLM later), so the report is checked
independently against the stored evidence. A report with any problem is rejected.

Report contract checked here:
- `## Sources` is a numbered list; each entry names one stored source by its `<URL>`, and
  may say "posted YYYY-MM-DD" only if that source states that publication date.
- Before `## Sources`: every `[n]` is a listed source; there are no Markdown links, autolinks
  or HTML; every “quote” followed by citations is verbatim evidence from a cited source.
- `## Findings` bullets are quotes of SUPPORTED claims, cited to a source that supports them.
- In `## Comparison matrix`, a "Supported" cell cites only sources supporting a SUPPORTED
  claim for that row's entity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.research import Claim, SourceOut, VerificationStatus
from app.sources.models import SourceKind
from app.verification.markdown import md, squash, unmd

_REF = re.compile(r"(?<!\\)\[(\d+)\]")
_QUOTE = re.compile(r"“((?:\\.|[^”\\])*)”((?:\s*(?<!\\)\[\d+\])*)")
_LINK = re.compile(r"(?<!\\)\]\(|(?<!\\)<(?:https?:|/|[a-zA-Z][\w-]*[\s>/])")
_URL_IN_LINE = re.compile(r"<([a-z][a-z0-9+.-]*://[^>\s]+)>")
_NUMBERED = re.compile(r"^(\d+)\. ")
_POSTED = re.compile(r"\bposted (\d{4}-\d{2}-\d{2})\b")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


@dataclass
class ReportCheck:
    problems: list[str] = field(default_factory=list)
    citations: int = 0
    quotes: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def _sections(markdown: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", markdown, flags=re.M)
    return {title.strip(): body for title, body in zip(parts[1::2], parts[2::2], strict=True)}


def check_report(markdown: str, claims: list[Claim], sources: list[SourceOut]) -> ReportCheck:
    result = ReportCheck()
    problems = result.problems
    by_url = {s.url: s for s in sources}
    if "## Sources" not in markdown:
        return ReportCheck(problems=["Report has no ## Sources section"])
    body, sources_text = markdown.split("## Sources", 1)
    sources_text = sources_text.split("\n## ", 1)[0]

    # 1. Source list: every <URL> is a stored source; numbered entries map citations.
    numbered: dict[int, SourceOut] = {}
    for line in sources_text.splitlines():
        if not (m := _URL_IN_LINE.search(line)):
            continue
        url = m.group(1)
        source = by_url.get(url)
        if source is None:
            problems.append(f"Source list URL is not a stored source: {url}")
            continue
        posted = _POSTED.search(line)
        stated = source.published_at.strftime("%Y-%m-%d") if source.published_at else None
        if posted and posted.group(1) != stated:
            problems.append(f"Source list shows a publication date {url} does not state")
        if numbered_line := _NUMBERED.match(line.strip()):
            n = int(numbered_line.group(1))
            if n in numbered:
                problems.append(f"Source number [{n}] is listed twice")
            numbered[n] = source
    if sorted(numbered) != list(range(1, len(numbered) + 1)):
        problems.append("Source numbers are not 1..N")

    # 2. Body: citations, links, quotes.
    refs_used = {int(n) for n in _REF.findall(body)}
    result.citations = len(_REF.findall(body))
    for n in sorted(refs_used - numbered.keys()):
        problems.append(f"Citation [{n}] does not match a listed source")
    if _LINK.search(body):
        problems.append("Report body contains a link or HTML outside the source list")

    evidence: dict[str, set[str]] = {}  # source id -> verbatim quotes (whitespace-squashed)
    for claim in claims:
        for span in claim.spans:
            evidence.setdefault(span.source_record_id, set()).add(squash(span.quote))
    for quote, refs in _QUOTE.findall(body):
        nums = {int(n) for n in _REF.findall(refs)}
        if not nums:
            continue
        result.quotes += 1
        text = squash(unmd(quote))
        if not any(text in evidence.get(numbered[n].id, ()) for n in nums if n in numbered):
            problems.append(f"Quote is not evidence from its cited source: “{text[:80]}”")

    sections = _sections(body)
    _check_findings(sections.get("Findings", ""), claims, numbered, problems)
    _check_matrix(sections.get("Comparison matrix", ""), claims, numbered, problems)
    return result


def _supporting_sources(claim: Claim, numbered: dict[int, SourceOut]) -> set[int]:
    ids = {s.source_record_id for s in claim.spans if s.stance == "supports"}
    return {
        n
        for n, src in numbered.items()
        if src.id in ids and src.source_kind is not SourceKind.COMMUNITY
    }


def _check_findings(
    text: str, claims: list[Claim], numbered: dict[int, SourceOut], problems: list[str]
) -> None:
    supported = [c for c in claims if c.verification_status is VerificationStatus.SUPPORTED]
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        m = _QUOTE.search(line)
        if not m or not _REF.findall(m.group(2)):
            problems.append(f"Finding without a quoted, cited claim: {line[:80]}")
            continue
        quote = squash(unmd(m.group(1)))
        nums = {int(n) for n in _REF.findall(m.group(2))}
        if not any(
            squash(c.claim_text) == quote and nums & _supporting_sources(c, numbered)
            for c in supported
        ):
            problems.append(f"Finding is not a supported claim with its source: “{quote[:80]}”")


def _check_matrix(
    text: str, claims: list[Claim], numbered: dict[int, SourceOut], problems: list[str]
) -> None:
    rows = [r for r in text.splitlines() if r.startswith("|") and not r.startswith("|---")]
    if not rows:
        return
    attributes = [unmd(c.strip()) for c in _CELL_SPLIT.split(rows[0].strip().strip("|"))][1:]
    labels = {md(c.entity): c.entity for c in claims if c.entity}
    for row in rows[1:]:
        cells = [c.strip() for c in _CELL_SPLIT.split(row.strip().strip("|"))]
        entity = labels.get(cells[0])
        for attribute, cell in zip(attributes, cells[1:], strict=False):
            if not cell.startswith("Supported"):
                continue
            nums = {int(n) for n in _REF.findall(cell)}
            backing = set().union(
                *(
                    _supporting_sources(c, numbered)
                    for c in claims
                    if c.entity == entity
                    and c.attribute == attribute
                    and c.verification_status is VerificationStatus.SUPPORTED
                )
            )
            if not nums or not nums <= backing:
                problems.append(
                    f"Matrix cell '{cells[0]} / {attribute}' says Supported without "
                    "matching evidence"
                )

"""Deterministic, rule-based stages for offline demos (LLM_PROVIDER=mock).

The mock analyst is purely extractive: every claim it makes is a sentence copied verbatim
from a stored source, with exact character offsets. It never paraphrases, so it can't
put words in a source's mouth. When nothing matches, it records an explicit unknown.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.research import (
    Claim,
    EvidenceSpan,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    SourceOut,
    ToolQuery,
    VerificationStatus,
)
from app.sources.models import SourceKind

OVERVIEW = "overview"
MAX_SENTENCE_CHARS = 400
MIN_SENTENCE_CHARS = 20
CLAIMS_PER_CELL = 2
CLAIMS_PER_QUESTION = 3

# Keywords match whole words; a trailing "*" means prefix match ("integrat*").
ATTRIBUTE_KEYWORDS: dict[str, list[str]] = {
    "pric": ["price*", "pricing", "cost*", "free tier", "free plan", "paid plan*", "paid",
             "per month", "per user", "subscription*", "freemium", "license*", "open source",
             "open-source"],
    "cost": ["price*", "pricing", "cost*", "free tier", "paid", "per month", "subscription*"],
    "api": ["api", "apis", "rest", "restful", "graphql", "sdk*", "endpoint*"],
    "content model": ["content model*", "schema*", "content type*", "field*", "structured"],
    "model": ["model*", "schema*", "content type*", "structured"],
    "integration": ["integrat*", "plugin*", "extension*", "webhook*", "ecosystem", "marketplace"],
    "developer": ["developer*", "typescript", "javascript", "node.js", "react", "cli",
                  "documentation", "docs", "learning curve", "easy to"],
    "host": ["host*", "self-host*", "cloud", "saas", "deploy*", "on-premise*"],
    "licen": ["license*", "licence*", "open source", "open-source", "mit", "gpl", "proprietary"],
    "open source": ["open source", "open-source", "license*", "github"],
}  # fmt: skip

STOPWORDS = frozenset(
    "what which when where does have with from that this they their there about into than "
    "them then were will would could should your for and the are how why who many much "
    "compare comparison between most best".split()
)


def _new_id() -> str:
    return uuid4().hex


# --- planner ---


class MockPlanner:
    """Turns the request into questions and a deduplicated list of tool calls."""

    def plan(self, request: ResearchRequest) -> ResearchPlan:
        attributes = request.attributes or [OVERVIEW]
        questions: list[ResearchQuestion] = []
        for entity in request.entities:
            for attribute in attributes:
                text = (
                    f"What is {entity}?"
                    if attribute == OVERVIEW
                    else f"What do sources say about the {attribute} of {entity}?"
                )
                questions.append(
                    ResearchQuestion(
                        id=f"q{len(questions) + 1}", text=text, entity=entity, attribute=attribute
                    )
                )
        for q in request.questions:
            questions.append(ResearchQuestion(id=f"q{len(questions) + 1}", text=q))
        if not questions:
            questions.append(ResearchQuestion(id="q1", text=f"What is {request.topic}?"))

        queries: list[ToolQuery] = []
        seen: set[tuple[str, str]] = set()

        def add(tool: str, query: str) -> None:
            key = (tool, query.casefold())
            if key not in seen:
                seen.add(key)
                queries.append(ToolQuery(tool=tool, query=query))

        for text in [request.topic, *request.entities, *request.questions]:
            add("wikipedia", text)
            add("hackernews", text)
        for url in request.user_urls:
            add("user_url", str(url))
        return ResearchPlan(questions=questions, queries=queries)


# --- analyst ---


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


def attribute_keywords(attribute: str) -> list[str]:
    key = attribute.casefold()
    words: list[str] = []
    for fragment, keywords in ATTRIBUTE_KEYWORDS.items():
        if fragment in key:
            words.extend(keywords)
    return words or [w for w in re.findall(r"\w{3,}", key)]


def _keyword_pattern(keywords: list[str]) -> re.Pattern[str]:
    parts = []
    for k in sorted(set(keywords), key=len, reverse=True):
        parts.append(re.escape(k[:-1]) if k.endswith("*") else re.escape(k) + r"(?!\w)")
    return re.compile(rf"(?<!\w)(?:{'|'.join(parts)})", re.IGNORECASE)


def _kind_rank(source: SourceOut) -> int:
    return 1 if source.source_kind is SourceKind.COMMUNITY else 0


class MockAnalyst:
    def analyze(
        self,
        request: ResearchRequest,
        plan: ResearchPlan,
        sources: list[SourceOut],
        contents: dict[str, str],
    ) -> list[Claim]:
        ordered = sorted(sources, key=_kind_rank)  # reference sources first
        claims: list[Claim] = []
        for question in plan.questions:
            if question.entity:
                claims.extend(self._entity_claims(question, ordered, contents))
            else:
                claims.extend(self._question_claims(question, ordered, contents))
        return claims

    def _entity_claims(
        self, question: ResearchQuestion, sources: list[SourceOut], contents: dict[str, str]
    ) -> list[Claim]:
        entity, attribute = question.entity or "", question.attribute or OVERVIEW
        names = entity_patterns(entity)
        keywords = (
            None if attribute == OVERVIEW else _keyword_pattern(attribute_keywords(attribute))
        )
        found: list[Claim] = []
        seen_quotes: set[str] = set()
        for source in sources:
            text = contents.get(source.id, "")
            for start, end in iter_sentences(text):
                sentence = text[start:end]
                if not any(p.search(sentence) for p in names):
                    continue
                if keywords is not None and not keywords.search(sentence):
                    continue
                if sentence in seen_quotes:
                    continue
                seen_quotes.add(sentence)
                found.append(_extractive_claim(entity, attribute, source.id, sentence, start, end))
                if len(found) >= CLAIMS_PER_CELL:
                    return found
        if not found:
            detail = "overview" if attribute == OVERVIEW else attribute
            found.append(
                Claim(
                    id=_new_id(),
                    entity=entity,
                    attribute=attribute,
                    claim_text=f"No retrieved source states the {detail} of {entity}.",
                    notes="Not found in retrieved sources; needs another source to verify.",
                )
            )
        return found

    def _question_claims(
        self, question: ResearchQuestion, sources: list[SourceOut], contents: dict[str, str]
    ) -> list[Claim]:
        words = [w for w in re.findall(r"\w{4,}", question.text.casefold()) if w not in STOPWORDS]
        needed = min(2, len(words))
        pattern = _keyword_pattern(words) if words else None
        found: list[Claim] = []
        for source in sources:
            text = contents.get(source.id, "")
            for start, end in iter_sentences(text):
                sentence = text[start:end]
                hits = (
                    {m.group(0).casefold() for m in pattern.finditer(sentence)}
                    if pattern
                    else set()
                )
                if needed and len(hits) >= needed:
                    found.append(
                        _extractive_claim(None, question.text, source.id, sentence, start, end)
                    )
                    if len(found) >= CLAIMS_PER_QUESTION:
                        return found
        if not found:
            found.append(
                Claim(
                    id=_new_id(),
                    entity=None,
                    attribute=question.text,
                    claim_text=f"No retrieved source answers: {question.text}",
                    notes="Not found in retrieved sources.",
                )
            )
        return found


def _extractive_claim(
    entity: str | None, attribute: str, source_id: str, sentence: str, start: int, end: int
) -> Claim:
    return Claim(
        id=_new_id(),
        entity=entity,
        attribute=attribute,
        claim_text=sentence,
        spans=[
            EvidenceSpan(
                id=_new_id(), source_record_id=source_id, quote=sentence, start=start, end=end
            )
        ],
    )


# --- writer ---

# Enough to stop links, images, HTML, emphasis and table breaks in quoted source text.
_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|~])")


def md(text: str) -> str:
    """Escape source text so it renders literally (no links, images, HTML or tables)."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(text.split()))


STATUS_LABEL = {
    VerificationStatus.SUPPORTED: "Supported",
    VerificationStatus.CONTRADICTED: "Conflicting",
    VerificationStatus.UNKNOWN: "Unknown",
}


class MockWriter:
    def write(
        self,
        request: ResearchRequest,
        plan: ResearchPlan,
        claims: list[Claim],
        sources: list[SourceOut],
        *,
        context: dict[str, str],
    ) -> str:
        by_id = {s.id: s for s in sources}
        numbers: dict[str, int] = {}

        def cite(claim: Claim) -> str:
            refs = []
            for span in claim.spans:
                if span.source_record_id in by_id:
                    n = numbers.setdefault(span.source_record_id, len(numbers) + 1)
                    refs.append(f"[{n}]")
            return "".join(dict.fromkeys(refs))

        supported = [c for c in claims if c.verification_status is VerificationStatus.SUPPORTED]
        conflicts = [c for c in claims if c.verification_status is VerificationStatus.CONTRADICTED]
        unknown = [c for c in claims if c.verification_status is VerificationStatus.UNKNOWN]
        generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        out = [f"# Research report: {md(request.topic)}", ""]
        out.append(
            f"Generated {generated} · Sources mode: {context.get('sources_mode', '?')} · "
            "Analysis: mock (extractive; no model inference)"
        )
        out += [
            "",
            "Every finding below quotes a stored source. Items without supporting "
            "evidence are listed under *Unknowns and gaps*.",
            "",
        ]

        out += ["## Research questions", ""]
        out += [f"{i}. {md(q.text)}" for i, q in enumerate(plan.questions, 1)] + [""]

        attributes = request.attributes or ["overview"]
        if request.entities:
            out += ["## Comparison matrix", ""]
            out.append("| Entity | " + " | ".join(md(a) for a in attributes) + " |")
            out.append("|---" * (len(attributes) + 1) + "|")
            for entity in request.entities:
                cells = []
                for attribute in attributes:
                    cell = [c for c in claims if c.entity == entity and c.attribute == attribute]
                    cells.append(self._cell(cell, cite))
                out.append(f"| {md(entity)} | " + " | ".join(cells) + " |")
            out += [
                "",
                "*Supported* needs a reference, user-provided URL or document source. "
                "*Unknown (community only)* means only Hacker News discussion mentions it.",
                "",
            ]

        out += ["## Findings", ""]
        if not supported:
            out += ["No claim could be verified against a non-community source.", ""]
        for group, items in _group(supported):
            out += [f"### {md(group)}", ""]
            out += [f"- “{md(c.claim_text)}” {cite(c)}" for c in items] + [""]

        out += ["## Unknowns and gaps", ""]
        if not unknown:
            out += ["None.", ""]
        for c in unknown:
            refs = cite(c)
            note = f" — {md(c.notes)}" if c.notes else ""
            text = f"“{md(c.claim_text)}” {refs}" if c.spans else md(c.claim_text)
            out.append(f"- {text}{note}")
        out.append("")

        out += ["## Conflicts", ""]
        if conflicts:
            out += [f"- {md(c.claim_text)} {cite(c)} — {md(c.notes or '')}" for c in conflicts]
        else:
            out.append("None detected. (The mock analyst does not search for contradictions yet.)")
        out.append("")

        out += ["## Sources", ""]
        cited = sorted(numbers.items(), key=lambda kv: kv[1])
        out += [f"{n}. {self._source_line(by_id[sid])}" for sid, n in cited]
        uncited = [s for s in sources if s.id not in numbers]
        if uncited:
            out += ["", "Also retrieved but not cited:", ""]
            out += [f"- {self._source_line(s)}" for s in uncited]
        out += [
            "",
            "## Method and limitations",
            "",
            "- Sources: Wikipedia (CC BY-SA 4.0), Hacker News discussion, and any "
            "user-provided URLs or documents. Retrieval dates are listed per source.",
            "- Findings are sentences quoted verbatim from those sources; they are not "
            "independently checked for accuracy or currency. Pricing and features change.",
            "- Hacker News content is community opinion and never verifies a fact alone.",
            "",
        ]
        return "\n".join(out)

    @staticmethod
    def _cell(claims: list[Claim], cite) -> str:
        if not claims:
            return "Unknown"
        supported = [c for c in claims if c.verification_status is VerificationStatus.SUPPORTED]
        if supported:
            return "Supported " + _refs(supported, cite)
        if any(c.verification_status is VerificationStatus.CONTRADICTED for c in claims):
            return "Conflicting " + _refs(claims, cite)
        community = [c for c in claims if c.spans]
        if community:
            return "Unknown (community only) " + _refs(community, cite)
        return "Unknown"

    @staticmethod
    def _source_line(s: SourceOut) -> str:
        retrieved = s.retrieved_at.strftime("%Y-%m-%d")
        parts = [f"{md(s.title)} — {s.source_name}", f"<{s.url}>", f"retrieved {retrieved}"]
        if s.published_at:
            parts.append(f"posted {s.published_at.strftime('%Y-%m-%d')}")
        if s.license:
            parts.append(md(s.license))
        return " · ".join(parts)


def _refs(claims: list[Claim], cite) -> str:
    """Citation markers for several claims, each source cited once."""
    return "".join(dict.fromkeys(m for c in claims for m in re.findall(r"\[\d+\]", cite(c))))


def _group(claims: list[Claim]) -> list[tuple[str, list[Claim]]]:
    groups: dict[str, list[Claim]] = {}
    for c in claims:
        label = f"{c.entity}: {c.attribute}" if c.entity else (c.attribute or "General")
        groups.setdefault(label, []).append(c)
    return list(groups.items())

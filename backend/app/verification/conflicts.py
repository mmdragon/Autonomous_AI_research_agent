"""Rule-based contradiction detection across sources.

For each entity, a few comparable facts ("slots") are extracted from every stored sentence
that names the entity. When two *different* sources give different values for the same
slot, one conflict claim is created: the best-ranked value is the claim (a verbatim
sentence, stance "supports"), and the best-ranked disagreeing sentence is attached with
stance "contradicts". The verifier then decides the status from which kinds of sources
are involved.

Slots are deliberately narrow so that a "conflict" means a real disagreement, not two
sentences that merely differ. Values that legitimately vary (prices across plans) are not
compared.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from app.schemas.research import Claim, EvidenceSpan, SourceOut
from app.sources.models import SourceKind
from app.verification.sentences import entity_patterns, iter_sentences

MAX_CORROBORATING = 2
_YEAR = r"\b(1[89]\d\d|20\d\d)\b"

_NOT_OPEN = re.compile(
    r"\b(?:not|no longer|isn't|is not|never been|ceased to be)\s+"
    r"(?:an?\s+|fully\s+)?open[- ]source\b",
    re.IGNORECASE,
)
_OPEN = re.compile(r"\bopen[- ]source\b", re.IGNORECASE)
_PROPRIETARY = re.compile(r"\b(?:proprietary|closed[- ]source)\b", re.IGNORECASE)
_FOUNDED = re.compile(rf"\b(?:founded|established|incorporated)\b[^.;]{{0,40}}?{_YEAR}", re.I)
_RELEASED = re.compile(
    r"\b(?:first released|initially released|initial release|first launched)\b"
    rf"[^.;]{{0,40}}?{_YEAR}",
    re.IGNORECASE,
)
_HQ = re.compile(r"\b(?:headquartered|headquarters) (?:is )?in ((?:[A-Z][\w-]+)(?: [A-Z][\w-]+)*)")


def _license(sentence: str) -> str | None:
    if _NOT_OPEN.search(sentence):
        return "proprietary"
    is_open, is_closed = bool(_OPEN.search(sentence)), bool(_PROPRIETARY.search(sentence))
    if is_open and not is_closed:
        return "open source"
    if is_closed and not is_open:
        return "proprietary"
    return None  # both or neither: ambiguous ("an open-source alternative to proprietary X")


def _group(pattern: re.Pattern[str]) -> Callable[[str], str | None]:
    def extract(sentence: str) -> str | None:
        match = pattern.search(sentence)
        return match.group(1) if match else None

    return extract


@dataclass(frozen=True)
class Slot:
    label: str
    extract: Callable[[str], str | None]

    def same(self, a: str, b: str) -> bool:
        a, b = a.casefold(), b.casefold()
        # "San Francisco" and "San Francisco, California" are not a disagreement.
        return a == b or a.startswith(b) or b.startswith(a)


SLOTS = (
    Slot("license model", _license),
    Slot("founding year", _group(_FOUNDED)),
    Slot("initial release year", _group(_RELEASED)),
    Slot("headquarters", _group(_HQ)),
)


@dataclass(frozen=True)
class Observation:
    value: str
    source: SourceOut
    start: int
    end: int
    quote: str

    @property
    def rank(self) -> int:
        return 1 if self.source.source_kind is SourceKind.COMMUNITY else 0


def _span(obs: Observation, stance: str) -> EvidenceSpan:
    return EvidenceSpan(
        id=uuid4().hex,
        source_record_id=obs.source.id,
        quote=obs.quote,
        start=obs.start,
        end=obs.end,
        stance=stance,
    )


def observe(entity: str, sources: list[SourceOut], contents: dict[str, str]):
    """Yield (slot, observation) for every slot value stated near the entity."""
    names = entity_patterns(entity)
    for source in sources:
        text = contents.get(source.id, "")
        for start, end in iter_sentences(text):
            sentence = text[start:end]
            if not any(p.search(sentence) for p in names):
                continue
            for slot in SLOTS:
                if (value := slot.extract(sentence)) is not None:
                    yield slot, Observation(value, source, start, end, sentence)


def detect_conflicts(
    entities: list[str], sources: list[SourceOut], contents: dict[str, str]
) -> list[Claim]:
    conflicts: list[Claim] = []
    for entity in entities:
        by_slot: dict[str, tuple[Slot, list[Observation]]] = {}
        for slot, obs in observe(entity, sources, contents):
            by_slot.setdefault(slot.label, (slot, []))[1].append(obs)
        for slot, observations in by_slot.values():
            if claim := _conflict(entity, slot, observations):
                conflicts.append(claim)
    return conflicts


def _conflict(entity: str, slot: Slot, observations: list[Observation]) -> Claim | None:
    ranked = sorted(observations, key=lambda o: o.rank)  # stable: source order within rank
    primary = ranked[0]
    opposing = [
        o
        for o in ranked
        if not slot.same(o.value, primary.value) and o.source.id != primary.source.id
    ]
    if not opposing:
        return None
    against = opposing[0]
    agreeing = [
        o
        for o in ranked[1:]
        if slot.same(o.value, primary.value) and o.source.id != primary.source.id
    ][:MAX_CORROBORATING]
    spans = [
        _span(primary, "supports"),
        *(_span(o, "supports") for o in agreeing),
        _span(against, "contradicts"),
    ]
    return Claim(
        id=uuid4().hex,
        entity=entity,
        attribute=slot.label,
        claim_text=primary.quote,
        spans=spans,
        notes=f"Sources disagree on the {slot.label} of {entity}: "
        f"{primary.value!r} vs {against.value!r}.",
    )

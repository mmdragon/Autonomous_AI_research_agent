"""Mechanical evidence check: no citation without a stored source and an exact quote.

Rules, applied in order:
1. A span is valid only if its source belongs to this run and its quote equals the stored
   source text at [start, end). Invalid spans are dropped and noted.
2. The claim text must be stated in a valid supporting quote (extractive check). A claim
   whose evidence doesn't contain it is UNKNOWN, however many spans it carries.
3. A contradicting span from a non-community source makes the claim CONTRADICTED.
4. Otherwise a supporting span from a non-community source (reference, user URL, document)
   makes it SUPPORTED. A community-only contradiction is noted as a dispute.
5. Community-only evidence leaves it UNKNOWN: Hacker News is opinion, not verification.
"""

from __future__ import annotations

from app.schemas.research import Claim, EvidenceSpan, SourceOut, VerificationStatus
from app.sources.models import SourceKind

COMMUNITY_ONLY_NOTE = (
    "Only community discussion (Hacker News) mentions this; treat as opinion, not verified fact."
)
NOT_STATED_NOTE = "The claim text is not stated in its evidence."
DISPUTED_NOTE = "Disputed in community discussion (Hacker News)."


def span_is_valid(span: EvidenceSpan, contents: dict[str, str]) -> bool:
    text = contents.get(span.source_record_id)
    if text is None or not (0 <= span.start < span.end <= len(text)):
        return False
    return text[span.start : span.end] == span.quote


def verify_claim(claim: Claim, kinds: dict[str, SourceKind], contents: dict[str, str]) -> Claim:
    valid = [s for s in claim.spans if s.source_record_id in kinds and span_is_valid(s, contents)]
    notes: list[str] = [claim.notes] if claim.notes else []

    def note(text: str) -> None:
        if text not in " ".join(notes):  # idempotent when a run re-verifies
            notes.append(text)

    if len(valid) < len(claim.spans):
        note(f"{len(claim.spans) - len(valid)} evidence span(s) failed the quote check.")

    def has(stance: str, *, community: bool | None = None) -> bool:
        return any(
            s.stance == stance
            and (
                community is None
                or (kinds[s.source_record_id] is SourceKind.COMMUNITY) == community
            )
            for s in valid
        )

    supports = [s for s in valid if s.stance == "supports"]
    if not valid or not supports:
        status = VerificationStatus.UNKNOWN
    elif not any(claim.claim_text in s.quote for s in supports):
        status = VerificationStatus.UNKNOWN
        note(NOT_STATED_NOTE)
    elif has("contradicts", community=False):
        status = VerificationStatus.CONTRADICTED
    elif has("supports", community=False):
        status = VerificationStatus.SUPPORTED
        if has("contradicts", community=True):
            note(DISPUTED_NOTE)
    else:
        status = VerificationStatus.UNKNOWN
        note(COMMUNITY_ONLY_NOTE)
        if has("contradicts"):
            note(DISPUTED_NOTE)

    return claim.model_copy(
        update={"spans": valid, "verification_status": status, "notes": " ".join(notes) or None}
    )


def verify_claims(
    claims: list[Claim], sources: list[SourceOut], contents: dict[str, str]
) -> list[Claim]:
    kinds = {s.id: s.source_kind for s in sources}
    return [verify_claim(c, kinds, contents) for c in claims]

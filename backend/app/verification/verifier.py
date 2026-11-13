"""Mechanical evidence check: no citation without a stored source and an exact quote.

Rules:
- A span is valid only if its source belongs to this run and the quote equals the stored
  source text at [start, end). Invalid spans are dropped and noted.
- A claim with no valid span is UNKNOWN.
- A contradicting span from a non-community source makes the claim CONTRADICTED.
- A claim is SUPPORTED only with a supporting span from a non-community source
  (reference, user URL or document). Community-only evidence leaves it UNKNOWN.
"""

from __future__ import annotations

from app.schemas.research import Claim, EvidenceSpan, SourceOut, VerificationStatus
from app.sources.models import SourceKind

COMMUNITY_ONLY_NOTE = (
    "Only community discussion (Hacker News) mentions this; treat as opinion, not verified fact."
)


def span_is_valid(span: EvidenceSpan, contents: dict[str, str]) -> bool:
    text = contents.get(span.source_record_id)
    if text is None or not (0 <= span.start < span.end <= len(text)):
        return False
    return text[span.start : span.end] == span.quote


def verify_claims(
    claims: list[Claim], sources: list[SourceOut], contents: dict[str, str]
) -> list[Claim]:
    kinds = {s.id: s.source_kind for s in sources}
    verified = []
    for claim in claims:
        valid = [
            s for s in claim.spans if s.source_record_id in kinds and span_is_valid(s, contents)
        ]
        notes = [claim.notes] if claim.notes else []
        if len(valid) < len(claim.spans):
            notes.append(
                f"{len(claim.spans) - len(valid)} evidence span(s) failed the quote check."
            )

        # Stances backed by a non-community source (reference, user URL, document).
        strong = {s.stance for s in valid if kinds[s.source_record_id] is not SourceKind.COMMUNITY}

        if not valid:
            status = VerificationStatus.UNKNOWN
        elif "contradicts" in strong:
            status = VerificationStatus.CONTRADICTED
        elif "supports" in strong:
            status = VerificationStatus.SUPPORTED
        else:
            status = VerificationStatus.UNKNOWN
            if COMMUNITY_ONLY_NOTE not in " ".join(notes):  # idempotent on re-verify
                notes.append(COMMUNITY_ONLY_NOTE)
        verified.append(
            claim.model_copy(
                update={
                    "spans": valid,
                    "verification_status": status,
                    "notes": " ".join(notes) or None,
                }
            )
        )
    return verified

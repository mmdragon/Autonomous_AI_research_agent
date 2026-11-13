from app.schemas.research import Claim, EvidenceSpan, VerificationStatus
from app.sources.models import SourceKind
from app.verification.verifier import (
    COMMUNITY_ONLY_NOTE,
    DISPUTED_NOTE,
    NOT_STATED_NOTE,
    span_is_valid,
    verify_claims,
)
from tests.test_mock_agents import source

TEXT = "Contentful is a headless CMS. It has a GraphQL API."
OTHER = "Contentful has no GraphQL API at all."
CONTENTS = {"wiki": TEXT, "hn": TEXT, "doc": OTHER, "hn2": OTHER}
SOURCES = [
    source("wiki"),
    source("hn", SourceKind.COMMUNITY),
    source("doc", SourceKind.DOCUMENT),
    source("hn2", SourceKind.COMMUNITY),
]
API = "It has a GraphQL API."


def claim(*spans: EvidenceSpan, text: str = API) -> Claim:
    return Claim(id="c", entity="Contentful", attribute="api", claim_text=text, spans=list(spans))


def span(sid="wiki", quote=API, start=30, end=51, stance="supports"):
    return EvidenceSpan(
        id=f"{sid}-{start}", source_record_id=sid, quote=quote, start=start, end=end, stance=stance
    )


def against(sid):
    return span(sid=sid, quote=OTHER, start=0, end=len(OTHER), stance="contradicts")


def verify(*spans, text=API):
    [c] = verify_claims([claim(*spans, text=text)], SOURCES, CONTENTS)
    return c


def test_exact_quote_from_reference_is_supported():
    assert TEXT[30:51] == API
    c = verify(span())
    assert c.verification_status is VerificationStatus.SUPPORTED
    assert c.notes is None


def test_claim_text_must_be_stated_in_its_evidence():
    c = verify(span(), text="Contentful has the best GraphQL API.")
    assert c.verification_status is VerificationStatus.UNKNOWN
    assert NOT_STATED_NOTE in c.notes
    assert verify(span(), text="GraphQL API").verification_status is VerificationStatus.SUPPORTED


def test_tampered_quote_is_dropped_and_claim_unknown():
    c = verify(span(quote="It has a free GraphQL API."))
    assert c.verification_status is VerificationStatus.UNKNOWN
    assert c.spans == []
    assert "failed the quote check" in c.notes


def test_out_of_range_and_foreign_sources_are_invalid():
    assert not span_is_valid(span(start=40, end=999), CONTENTS)
    [c] = verify_claims([claim(span(sid="other-run"))], SOURCES, {**CONTENTS, "other-run": TEXT})
    assert c.spans == [] and c.verification_status is VerificationStatus.UNKNOWN


def test_community_only_evidence_stays_unknown_with_note_once():
    c = verify(span(sid="hn"))
    assert c.verification_status is VerificationStatus.UNKNOWN
    assert len(c.spans) == 1
    [again] = verify_claims([c], SOURCES, CONTENTS)
    assert again.notes.count(COMMUNITY_ONLY_NOTE) == 1


def test_non_community_contradiction_makes_claim_contradicted():
    assert verify(span(), against("doc")).verification_status is VerificationStatus.CONTRADICTED
    # A document contradicting community-only support is still a contradiction.
    c = verify(span(sid="hn"), against("doc"))
    assert c.verification_status is VerificationStatus.CONTRADICTED


def test_community_contradiction_is_only_a_dispute():
    c = verify(span(), against("hn2"))
    assert c.verification_status is VerificationStatus.SUPPORTED
    assert DISPUTED_NOTE in c.notes
    c = verify(span(sid="hn"), against("hn2"))
    assert c.verification_status is VerificationStatus.UNKNOWN
    assert COMMUNITY_ONLY_NOTE in c.notes and DISPUTED_NOTE in c.notes


def test_contradiction_alone_is_not_support():
    assert verify(against("doc")).verification_status is VerificationStatus.UNKNOWN


def test_no_spans_is_unknown():
    assert verify().verification_status is VerificationStatus.UNKNOWN

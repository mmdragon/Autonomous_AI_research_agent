from app.schemas.research import Claim, EvidenceSpan, VerificationStatus
from app.sources.models import SourceKind
from app.verification.verifier import COMMUNITY_ONLY_NOTE, span_is_valid, verify_claims
from tests.test_mock_agents import source

TEXT = "Contentful is a headless CMS. It has a GraphQL API."
CONTENTS = {"wiki": TEXT, "hn": TEXT}
SOURCES = [source("wiki"), source("hn", SourceKind.COMMUNITY)]


def claim(*spans: EvidenceSpan) -> Claim:
    return Claim(id="c", entity="Contentful", attribute="api", claim_text="x", spans=list(spans))


def span(sid="wiki", quote="It has a GraphQL API.", start=30, end=51, stance="supports"):
    return EvidenceSpan(
        id=f"{sid}-{start}", source_record_id=sid, quote=quote, start=start, end=end, stance=stance
    )


def test_exact_quote_from_reference_is_supported():
    assert TEXT[30:51] == "It has a GraphQL API."
    [c] = verify_claims([claim(span())], SOURCES, CONTENTS)
    assert c.verification_status is VerificationStatus.SUPPORTED
    assert c.notes is None


def test_tampered_quote_is_dropped_and_claim_unknown():
    [c] = verify_claims([claim(span(quote="It has a free GraphQL API."))], SOURCES, CONTENTS)
    assert c.verification_status is VerificationStatus.UNKNOWN
    assert c.spans == []
    assert "failed the quote check" in c.notes


def test_out_of_range_and_foreign_sources_are_invalid():
    assert not span_is_valid(span(start=40, end=999), CONTENTS)
    [c] = verify_claims([claim(span(sid="other-run"))], SOURCES, {**CONTENTS, "other-run": TEXT})
    assert c.spans == [] and c.verification_status is VerificationStatus.UNKNOWN


def test_community_only_evidence_stays_unknown_with_note_once():
    [c] = verify_claims([claim(span(sid="hn"))], SOURCES, CONTENTS)
    assert c.verification_status is VerificationStatus.UNKNOWN
    assert len(c.spans) == 1
    [again] = verify_claims([c], SOURCES, CONTENTS)
    assert again.notes.count(COMMUNITY_ONLY_NOTE) == 1


def test_reference_contradiction_wins():
    spans = (span(), span(stance="contradicts", start=0, end=29, quote=TEXT[:29]))
    [c] = verify_claims([claim(*spans)], SOURCES, CONTENTS)
    assert c.verification_status is VerificationStatus.CONTRADICTED


def test_no_spans_is_unknown():
    [c] = verify_claims([claim()], SOURCES, CONTENTS)
    assert c.verification_status is VerificationStatus.UNKNOWN

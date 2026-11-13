from app.sources.models import SourceKind
from app.verification.conflicts import SLOTS, detect_conflicts
from app.verification.verifier import verify_claims
from tests.test_mock_agents import source

SLOT = {s.label: s for s in SLOTS}


def test_license_extraction_handles_negation_and_ambiguity():
    lic = SLOT["license model"].extract
    assert lic("Strapi is an open-source headless CMS.") == "open source"
    assert lic("Contentful is not open source.") == "proprietary"
    assert lic("Contentful is a proprietary SaaS product.") == "proprietary"
    assert lic("Directus is an open-source alternative to proprietary CMSs.") is None
    assert lic("Sanity has a hosted backend.") is None


def test_year_and_headquarters_extraction():
    assert SLOT["founding year"].extract("Contentful was founded in Berlin in 2013.") == "2013"
    assert SLOT["initial release year"].extract("Strapi was first released in 2015.") == "2015"
    hq = SLOT["headquarters"].extract
    assert hq("The company is headquartered in San Francisco.") == "San Francisco"
    assert SLOT["headquarters"].same("San Francisco", "San Francisco California")


def test_cross_source_disagreement_becomes_a_conflict_claim():
    contents = {
        "wiki": "Contentful was founded in 2013 by two engineers.",
        "doc": "Contentful was founded in 2011 in Berlin.",
        "wiki2": "Records show Contentful was founded in 2013.",
    }
    sources = [source("wiki"), source("doc", SourceKind.DOCUMENT), source("wiki2")]
    [conflict] = detect_conflicts(["Contentful"], sources, contents)
    assert conflict.attribute == "founding year"
    assert conflict.claim_text == contents["wiki"]
    stances = [(s.source_record_id, s.stance) for s in conflict.spans]
    assert stances == [("wiki", "supports"), ("wiki2", "supports"), ("doc", "contradicts")]
    assert "'2013' vs '2011'" in conflict.notes
    for s in conflict.spans:
        assert contents[s.source_record_id][s.start : s.end] == s.quote

    [verified] = verify_claims([conflict], sources, contents)
    assert verified.verification_status == "contradicted"


def test_reference_value_is_preferred_over_community():
    contents = {
        "hn": "Strapi is not open source anymore, sadly.",
        "wiki": "Strapi is an open-source headless CMS.",
    }
    sources = [source("hn", SourceKind.COMMUNITY), source("wiki")]
    [conflict] = detect_conflicts(["Strapi"], sources, contents)
    assert conflict.claim_text == contents["wiki"]
    [verified] = verify_claims([conflict], sources, contents)
    assert verified.verification_status == "supported"
    assert "Disputed in community discussion" in verified.notes


def test_no_conflict_within_one_source_or_on_agreement():
    one_source = {"wiki": "Strapi was founded in 2015. Strapi was founded in 2016 per others."}
    assert detect_conflicts(["Strapi"], [source("wiki")], one_source) == []
    agree = {"a": "Strapi is open source software.", "b": "Strapi is fully open-source."}
    assert detect_conflicts(["Strapi"], [source("a"), source("b")], agree) == []


def test_only_sentences_naming_the_entity_count():
    contents = {"a": "Strapi is open source software.", "b": "Contentful is proprietary."}
    assert detect_conflicts(["Strapi"], [source("a"), source("b")], contents) == []

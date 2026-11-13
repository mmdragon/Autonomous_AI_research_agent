import pytest

from tests.test_engine import DEMO, RECORDED

NOTE = b"# Team notes\n\nContentful was founded in 2011 in Berlin, according to our notes.\n"


def upload(client, name="notes.md", data=NOTE, content_type="text/markdown"):
    return client.post("/api/documents", files={"file": (name, data, content_type)})


def test_upload_returns_document_and_dedupes(client):
    r = upload(client)
    assert r.status_code == 201
    doc = r.json()
    assert doc["filename"] == "notes.md" and doc["size_bytes"] == len(NOTE)
    assert doc["excerpt"].startswith("# Team notes")
    assert upload(client).json()["id"] == doc["id"]
    assert upload(client, name="other.md").json()["id"] != doc["id"]


def test_upload_strips_client_directories(client):
    assert upload(client, name="../../etc/notes.txt").json()["filename"] == "notes.txt"


@pytest.mark.parametrize(
    "name, data, code",
    [
        ("tool.exe", b"MZ...", 422),
        ("bad.txt", b"\xff\xfe\x00\x00broken", 422),
        ("empty.md", b"   ", 422),
    ],
)
def test_upload_rejections(client, name, data, code):
    assert upload(client, name=name, data=data).status_code == code


def test_upload_size_limit(client, settings):
    big = b"a" * (settings.max_upload_bytes + 1)
    assert upload(client, name="big.txt", data=big).status_code == 413


def test_run_rejects_unknown_or_malformed_document_ids(client):
    r = client.post("/api/runs", json={"topic": "cms", "document_ids": ["0" * 32]})
    assert r.status_code == 422 and "Unknown document" in r.json()["detail"]
    assert (
        client.post("/api/runs", json={"topic": "cms", "document_ids": ["../x"]}).status_code == 422
    )


@pytest.mark.skipif(not any(RECORDED.glob("*.json")), reason="no recorded fixtures")
def test_document_source_can_contradict_wikipedia(client):
    doc_id = upload(client).json()["id"]
    payload = DEMO.model_dump(mode="json") | {"document_ids": [doc_id]}
    run_id = client.post("/api/runs", json=payload).json()["id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "completed"

    doc_source = next(s for s in detail["sources"] if s["source_kind"] == "document")
    assert doc_source["url"].endswith("/notes.md")
    conflict = next(c for c in detail["claims"] if c["attribute"] == "founding year")
    assert conflict["entity"] == "Contentful"
    assert conflict["verification_status"] == "contradicted"
    stances = {s["source_record_id"]: s["stance"] for s in conflict["spans"]}
    assert stances[doc_source["id"]] == "contradicts"

    calls = client.get(f"/api/runs/{run_id}/tool-calls").json()
    assert any(c["tool"] == "document.load" and c["status"] == "ok" for c in calls)
    report = client.get(f"/api/runs/{run_id}/report").json()["markdown"]
    conflicts = report.split("## Conflicts")[1].split("## Sources")[0]
    assert "**Contentful: founding year** (Sources disagree)" in conflicts
    assert "founded in 2011" in conflicts and "founded in 2013" in conflicts


@pytest.mark.skipif(not any(RECORDED.glob("*.json")), reason="no recorded fixtures")
def test_user_documents_are_kept_under_a_small_source_limit(client):
    doc_id = upload(client).json()["id"]
    payload = DEMO.model_dump(mode="json") | {"document_ids": [doc_id], "max_sources": 2}
    run_id = client.post("/api/runs", json=payload).json()["id"]
    sources = client.get(f"/api/runs/{run_id}").json()["sources"]
    assert len(sources) == 2
    assert sources[0]["source_kind"] == "document"

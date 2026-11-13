import pytest

from app.repositories.db import init_db
from app.repositories.runs import RunRepository
from tests.test_engine import DEMO, RECORDED

pytestmark = pytest.mark.skipif(not any(RECORDED.glob("*.json")), reason="no recorded fixtures")


def test_create_run_executes_in_background_and_exposes_results(client):
    r = client.post("/api/runs", json=DEMO.model_dump(mode="json"))
    assert r.status_code == 202
    run_id = r.json()["id"]

    # TestClient runs background tasks before returning, so the run is finished here.
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "completed"
    assert [s["stage"] for s in detail["steps"]] == [
        "plan",
        "research",
        "analyze",
        "verify",
        "write",
    ]
    assert detail["plan"]["questions"] and detail["sources"] and detail["claims"]
    assert detail["has_report"] is True
    cited = [c for c in detail["claims"] if c["spans"]]
    assert all(c["source_record_ids"] for c in cited)
    source_ids = {s["id"] for s in detail["sources"]}
    assert all(set(c["source_record_ids"]) <= source_ids for c in cited)
    assert "content" not in detail["sources"][0]  # full text is not sent to the browser

    assert client.get("/api/runs").json()[0]["id"] == run_id
    calls = client.get(f"/api/runs/{run_id}/tool-calls").json()
    assert calls and {"tool", "request", "status", "http_requests"} <= calls[0].keys()

    report = client.get(f"/api/runs/{run_id}/report").json()
    assert report["markdown"].startswith("# Research report: headless CMS")
    download = client.get(f"/api/runs/{run_id}/report.md")
    assert download.headers["content-type"].startswith("text/markdown")
    assert "attachment" in download.headers["content-disposition"]


def test_resume_rules(client):
    run_id = client.post("/api/runs", json={"topic": "nothing recorded here"}).json()["id"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"
    assert client.get(f"/api/runs/{run_id}/report").status_code == 404
    r = client.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 202
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"  # still no sources

    done = client.post("/api/runs", json=DEMO.model_dump(mode="json")).json()["id"]
    assert client.post(f"/api/runs/{done}/resume").status_code == 409


def test_unknown_run_is_404(client):
    for path in ("", "/tool-calls", "/report", "/report.md"):
        assert client.get(f"/api/runs/nope{path}").status_code == 404
    assert client.post("/api/runs/nope/resume").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"topic": "x"},
        {"topic": "cms", "entities": [f"e{i}" for i in range(9)]},
        {"topic": "cms", "max_sources": 26},
        {"topic": "cms", "user_urls": ["ftp://x.test/"]},
        {"topic": "cms", "output_format": "pdf"},
    ],
)
def test_request_validation(client, payload):
    assert client.post("/api/runs", json=payload).status_code == 422


def test_startup_marks_interrupted_runs_failed(settings):
    init_db(settings.database_path)
    repo = RunRepository(settings.database_path)
    run_id = repo.create_run(DEMO)
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings)):
        pass
    assert repo.get_summary(run_id).status == "failed"
    assert repo.get_summary(run_id).error == "Interrupted by server restart"

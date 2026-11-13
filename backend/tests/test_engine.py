"""End-to-end workflow tests, offline against the recorded fixtures."""

import re

import pytest

from app.config import BACKEND_ROOT, Settings
from app.repositories.db import init_db
from app.repositories.runs import RunRepository
from app.schemas.research import ResearchRequest, RunStatus, Stage, StepStatus
from app.sources.registry import build_source_tools
from app.verification.verifier import span_is_valid
from app.workflows.engine import WorkflowEngine
from app.workflows.factory import build_agents

RECORDED = BACKEND_ROOT / "fixtures" / "http"
DEMO = ResearchRequest(
    topic="headless CMS",
    entities=["Strapi", "Contentful", "Sanity CMS", "Directus", "Payload CMS"],
    attributes=[
        "content modeling",
        "API options",
        "integrations",
        "developer experience",
        "pricing",
    ],
    max_sources=15,
)

pytestmark = pytest.mark.skipif(not any(RECORDED.glob("*.json")), reason="no recorded fixtures")


class Harness:
    def __init__(self, tmp_path, **overrides):
        self.settings = Settings(
            _env_file=None,
            database_path=tmp_path / "db.sqlite3",
            fixtures_dir=RECORDED,
            **overrides,
        )
        init_db(self.settings.database_path)
        self.repo = RunRepository(self.settings.database_path)
        self.agents = build_agents(self.settings)
        self.clock_value = 0.0

    def engine(self, **overrides) -> WorkflowEngine:
        settings = self.settings.model_copy(update=overrides)
        return WorkflowEngine(
            self.repo,
            build_source_tools(settings),
            self.agents,
            settings,
            clock=lambda: self.clock_value,
        )

    def stages(self, run_id):
        return [(s.stage, s.status) for s in self.repo.list_steps(run_id)]


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


def test_demo_run_completes_with_every_citation_backed(h):
    run_id = h.repo.create_run(DEMO)
    assert h.engine().run(run_id) is RunStatus.COMPLETED
    assert h.stages(run_id) == [(s, StepStatus.COMPLETED) for s in Stage]

    sources = {s.id: s for s in h.repo.list_sources(run_id)}
    assert 0 < len(sources) <= 15
    contents = h.repo.source_contents(run_id)
    claims = h.repo.list_claims(run_id)
    assert claims
    for c in claims:
        for span in c.spans:
            assert span_is_valid(span, contents), c.claim_text
        if c.verification_status == "supported":
            assert any(sources[s.source_record_id].source_kind != "community" for s in c.spans)

    report = h.repo.latest_report(run_id).markdown
    cited = {int(n) for n in re.findall(r"^(\d+)\. ", report.split("## Sources")[1], re.M)}
    used = {int(n) for n in re.findall(r"\[(\d+)\]", report.split("## Sources")[0])}
    assert used and used == cited  # every [n] resolves to a listed source, none unused
    for url in re.findall(r"<(https?://[^>]+)>", report):
        assert url in {s.url for s in sources.values()}  # no URL that isn't a stored source
    assert "## Unknowns and gaps" in report and "No retrieved source states" in report
    assert "Atlantic jackknife clam" not in report.split("Also retrieved")[0]


def test_tool_calls_are_logged_with_http_counts(h):
    run_id = h.repo.create_run(DEMO)
    h.engine().run(run_id)
    calls = h.repo.list_tool_calls(run_id)
    assert {c.tool for c in calls} == {
        "wikipedia.search",
        "wikipedia.fetch",
        "hackernews.search",
        "hackernews.fetch",
    }
    assert all(c.status == "ok" and c.http_requests >= 1 for c in calls)
    hn_fetch = next(c for c in calls if c.tool == "hackernews.fetch")
    assert hn_fetch.http_requests > 1  # story plus comments


def test_failed_queries_are_logged_and_research_continues(h):
    run_id = h.repo.create_run(ResearchRequest(topic="headless CMS", entities=["Unrecorded Thing"]))
    assert h.engine().run(run_id) is RunStatus.COMPLETED
    errors = [c for c in h.repo.list_tool_calls(run_id) if c.status == "error"]
    assert errors and all("offline" in c.error for c in errors)
    claims = h.repo.list_claims(run_id)
    assert all(c.verification_status == "unknown" for c in claims if c.entity)


def test_run_fails_clearly_when_no_source_is_found(h):
    run_id = h.repo.create_run(ResearchRequest(topic="nothing recorded here"))
    assert h.engine().run(run_id) is RunStatus.FAILED
    summary = h.repo.get_summary(run_id)
    assert summary.error.startswith("research failed: No sources retrieved")
    assert h.stages(run_id)[-1] == (Stage.RESEARCH, StepStatus.FAILED)
    assert h.repo.latest_report(run_id) is None


def test_tool_call_limit_stops_run_and_resume_continues(h):
    run_id = h.repo.create_run(DEMO)
    assert h.engine(max_tool_calls_per_run=5).run(run_id) is RunStatus.FAILED
    assert "Tool call limit reached (5)" in h.repo.get_summary(run_id).error

    assert h.engine().resume(run_id) is RunStatus.COMPLETED
    stages = h.stages(run_id)
    assert stages.count((Stage.PLAN, StepStatus.COMPLETED)) == 1  # plan was not redone
    assert stages[1] == (Stage.RESEARCH, StepStatus.FAILED)
    assert h.repo.latest_report(run_id) is not None


def test_step_limit_is_enforced(h):
    run_id = h.repo.create_run(DEMO)
    assert h.engine(max_steps_per_run=2).run(run_id) is RunStatus.FAILED
    assert "Step limit reached (2)" in h.repo.get_summary(run_id).error
    assert len(h.repo.list_steps(run_id)) == 2


def test_run_time_limit_is_enforced(h):
    run_id = h.repo.create_run(DEMO)
    engine = h.engine(max_run_seconds=10)
    original = engine._plan

    def slow_plan(*args):
        h.clock_value += 11  # simulated time passes during planning
        return original(*args)

    engine._plan = slow_plan
    assert engine.run(run_id) is RunStatus.FAILED
    assert "Run time limit reached (10s)" in h.repo.get_summary(run_id).error


def test_unexpected_crash_is_contained_and_resumable(h):
    class Boom:
        def analyze(self, *args):
            raise RuntimeError("secret internal detail")

    run_id = h.repo.create_run(DEMO)
    engine = h.engine()
    engine.agents = type(h.agents)(h.agents.planner, Boom(), h.agents.writer)
    assert engine.run(run_id) is RunStatus.FAILED
    error = h.repo.get_summary(run_id).error
    assert error == "analyze failed: Internal error (RuntimeError)"
    assert "secret" not in error

    assert h.engine().resume(run_id) is RunStatus.COMPLETED
    assert [s for s, _ in h.stages(run_id)].count(Stage.RESEARCH) == 1


def test_run_and_resume_only_from_valid_states(h):
    run_id = h.repo.create_run(DEMO)
    assert h.engine().resume(run_id) is RunStatus.PENDING  # not failed: nothing happens
    assert h.repo.list_steps(run_id) == []
    h.engine().run(run_id)
    assert h.engine().run(run_id) is RunStatus.COMPLETED  # already done: no new steps
    assert len(h.repo.list_steps(run_id)) == 5


def test_interrupted_runs_are_marked_failed(h):
    run_id = h.repo.create_run(DEMO)
    h.repo.claim_for_execution(run_id, {RunStatus.PENDING})
    step = h.repo.start_step(run_id, Stage.PLAN, "x")
    assert h.repo.fail_interrupted_runs() == 1
    assert h.repo.get_summary(run_id).status is RunStatus.FAILED
    assert h.repo.list_steps(run_id)[0].status is StepStatus.FAILED
    assert h.repo.list_steps(run_id)[0].id == step
    assert h.engine().resume(run_id) is RunStatus.COMPLETED


def test_sources_are_deduplicated_and_capped(h):
    request = DEMO.model_copy(update={"max_sources": 4})
    run_id = h.repo.create_run(request)
    h.engine().run(run_id)
    sources = h.repo.list_sources(run_id)
    assert len(sources) == 4
    assert len({s.url for s in sources}) == 4

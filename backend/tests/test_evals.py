"""The offline evaluation suite must pass, and must catch a broken agent."""

import pytest

from app.agents.mock import MockWriter
from app.schemas.research import VerificationStatus
from evals.run import evaluate, run_all
from evals.tasks import TASKS
from tests.test_engine import RECORDED

pytestmark = pytest.mark.skipif(not any(RECORDED.glob("*.json")), reason="no recorded fixtures")
TASK = {t.id: t for t in TASKS}


def test_all_eval_tasks_pass_and_are_repeatable():
    results = run_all()
    failures = {
        r.task.id: [c.name for c in r.checks if not c.passed] for r in results if not r.passed
    }
    assert not failures
    assert all(r.repeatable for r in results)


def test_suite_catches_a_lenient_verifier(monkeypatch):
    def everything_supported(claims, sources, contents):
        return [
            c.model_copy(update={"verification_status": VerificationStatus.SUPPORTED})
            for c in claims
        ]

    monkeypatch.setattr("app.workflows.engine.verify_claims", everything_supported)
    result = evaluate(TASK["cms-comparison"])
    failed = {c.name for c in result.checks if not c.passed}
    assert not result.passed
    assert "no unsupported claims" in failed
    assert "nothing about Strapi marked supported" in failed


def test_suite_catches_a_fabricating_writer(monkeypatch):
    original = MockWriter.write

    def fabricate(self, *args, **kwargs):
        report = original(self, *args, **kwargs)
        return report.replace(
            "## Sources\n", "## Sources\n\n1. Vendor site <https://fake.example>\n", 1
        )

    monkeypatch.setattr(MockWriter, "write", fabricate)
    result = evaluate(TASK["cms-comparison"])
    failed = {c.name for c in result.checks if not c.passed}
    assert "status is completed" in failed and "report saved = True" in failed
    assert result.metrics.failed_stages == ["write"]

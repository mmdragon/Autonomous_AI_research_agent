"""Run the offline evaluation suite.

    uv run python -m evals.run                  # run all tasks, print results
    uv run python -m evals.run --update-docs    # also refresh docs/evaluation.md and README
    uv run python -m evals.run --task no-sources

Each task runs twice in fresh temporary databases against the recorded fixtures with the mock
analyst: no network, no API keys, no cost. A task passes when every expectation holds and both
runs produce the same outcome fingerprint. Exit code 1 if any task fails.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.config import BACKEND_ROOT, Settings
from app.repositories.db import init_db
from app.repositories.runs import RunRepository
from app.schemas.research import RunStatus
from app.sources.documents import load_document
from app.sources.registry import build_source_tools
from app.verification.markdown import unmd
from app.workflows.engine import WorkflowEngine
from app.workflows.factory import build_agents
from evals.metrics import RunMetrics, cells, compute, is_conflict
from evals.tasks import TASKS, EvalTask, Expect

PROJECT_ROOT = BACKEND_ROOT.parent
DOCS_PATH = PROJECT_ROOT / "docs" / "evaluation.md"
README_PATH = PROJECT_ROOT / "README.md"
RESULTS_PATH = BACKEND_ROOT / "evals" / "results" / "latest.json"
README_START, README_END = "<!-- eval:start -->", "<!-- eval:end -->"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class TaskResult:
    task: EvalTask
    metrics: RunMetrics
    checks: list[Check] = field(default_factory=list)
    repeatable: bool = False
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.repeatable and all(c.passed for c in self.checks)


# --- running ---


def _settings(workdir: Path, overrides: dict) -> Settings:
    return Settings(
        _env_file=None,
        database_path=workdir / "eval.sqlite3",
        sources_mode="fixtures",
        llm_provider="mock",
        fixtures_dir=BACKEND_ROOT / "fixtures" / "http",
        **overrides,
    )


def _execute(engine_settings: Settings, repo: RunRepository, run_id: str, resume: bool) -> None:
    tools = build_source_tools(engine_settings)
    try:
        engine = WorkflowEngine(repo, tools, build_agents(engine_settings), engine_settings)
        engine.resume(run_id) if resume else engine.run(run_id)
    finally:
        tools.close()


def run_once(task: EvalTask) -> tuple[RunRepository, str, RunMetrics, RunMetrics | None]:
    """Returns (repo, run_id, first-attempt metrics, metrics after resume or None)."""
    workdir = Path(tempfile.mkdtemp(prefix=f"eval-{task.id}-"))
    settings = _settings(workdir, task.settings)
    init_db(settings.database_path)
    repo = RunRepository(settings.database_path)

    document_ids = []
    for filename, text in task.documents.items():
        data = text.encode()
        record = load_document(filename, data, max_bytes=settings.max_upload_bytes)
        document_ids.append(repo.save_document(record, record.title, data).id)
    request = task.request.model_copy(update={"document_ids": document_ids})

    run_id = repo.create_run(request)
    _execute(settings, repo, run_id, resume=False)
    first = compute(repo, run_id)
    resumed = None
    if task.resume_expect is not None:
        _execute(_settings(workdir, {}), repo, run_id, resume=True)
        resumed = compute(repo, run_id)
    return repo, run_id, first, resumed


# --- checking ---


def _cited_titles(report: str) -> set[str]:
    section = report.split("## Sources", 1)[-1].split("Also retrieved", 1)[0]
    return {unmd(m.group(1)) for m in re.finditer(r"^\d+\. (.+?) — ", section, re.M)}


def check(expect: Expect, repo: RunRepository, run_id: str, m: RunMetrics, label: str = ""):
    request = repo.get_request(run_id)
    claims = repo.list_claims(run_id)
    report = repo.latest_report(run_id)
    p = f"{label}: " if label else ""
    out: list[Check] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        out.append(Check(p + name, ok, detail))

    add(f"status is {expect.status}", m.status == expect.status, m.error or "")
    if expect.failed_stage:
        add(
            f"{expect.failed_stage} stage failed",
            expect.failed_stage in m.failed_stages,
            ", ".join(m.failed_stages),
        )
    if expect.error_contains:
        add(
            f"error mentions '{expect.error_contains}'",
            expect.error_contains in (m.error or ""),
            m.error or "",
        )
    add(f"report saved = {expect.report}", m.report_saved == expect.report)
    add(
        "report passes evidence check",
        not m.report_check_problems,
        "; ".join(m.report_check_problems[:3]),
    )
    add("no unsupported claims", m.unsupported_claims == 0, f"{m.unsupported_claims} found")
    if expect.min_sources:
        add(f"≥ {expect.min_sources} sources", m.sources >= expect.min_sources, str(m.sources))
    if expect.max_sources is not None:
        add(f"≤ {expect.max_sources} sources", m.sources <= expect.max_sources, str(m.sources))
    for kind, n in expect.source_kinds.items():
        got = m.sources_by_kind.get(kind, 0)
        add(f"≥ {n} {kind} source(s)", got >= n, str(got))
    if expect.cited_titles or expect.not_cited_titles:
        cited = _cited_titles(report.markdown) if report else set()
        for title in expect.cited_titles:
            add(f"cites '{title}'", title in cited)
        for title in expect.not_cited_titles:
            add(f"does not cite '{title}'", title not in cited)
    grid = cells(request, claims)
    for key, status in expect.cells.items():
        entity, attribute = key.split("|", 1)
        got = grid.get((entity, attribute), "missing")
        add(f"{entity} / {attribute} is {status}", got == status, got)
    for entity in expect.never_supported_entities:
        bad = [c for c in claims if c.entity == entity and c.verification_status == "supported"]
        add(f"nothing about {entity} marked supported", not bad, f"{len(bad)} supported")
    found = [c for c in claims if is_conflict(c)]
    for want in expect.conflicts:
        hit = [c for c in found if c.entity == want["entity"] and c.attribute == want["attribute"]]
        ok = any(c.verification_status == want["status"] for c in hit)
        add(
            f"conflict: {want['entity']} {want['attribute']} {want['status']}",
            ok,
            ", ".join(c.verification_status for c in hit) or "not found",
        )
    if expect.max_conflicts is not None:
        add(
            f"≤ {expect.max_conflicts} conflicts",
            m.conflicts <= expect.max_conflicts,
            str(m.conflicts),
        )
    if expect.min_supported_claims:
        add(
            f"≥ {expect.min_supported_claims} supported claim(s)",
            m.supported_claims >= expect.min_supported_claims,
            str(m.supported_claims),
        )
    if expect.min_entity_coverage is not None:
        add(
            f"entity coverage ≥ {expect.min_entity_coverage:.0%}",
            (m.entity_coverage or 0) >= expect.min_entity_coverage,
            f"{m.entity_coverage:.0%}" if m.entity_coverage is not None else "n/a",
        )
    if expect.min_tool_errors:
        add(
            f"≥ {expect.min_tool_errors} failed tool call(s) logged",
            m.tool_errors >= expect.min_tool_errors,
            str(m.tool_errors),
        )
    if expect.max_tool_errors is not None:
        add(
            f"≤ {expect.max_tool_errors} failed tool calls",
            m.tool_errors <= expect.max_tool_errors,
            str(m.tool_errors),
        )
    if expect.min_tool_blocked:
        add(
            f"≥ {expect.min_tool_blocked} blocked call(s)",
            m.tool_blocked >= expect.min_tool_blocked,
            str(m.tool_blocked),
        )
    return out


def evaluate(task: EvalTask) -> TaskResult:
    started = time.perf_counter()
    repo, run_id, first, resumed = run_once(task)
    final = resumed or first
    checks = check(task.expect, repo, run_id, first, "first attempt" if resumed else "")
    if task.resume_expect is not None and resumed is not None:
        checks += check(task.resume_expect, repo, run_id, resumed, "after resume")
        plans = [s for s in repo.list_steps(run_id) if s.stage == "plan"]
        checks.append(Check("after resume: plan not repeated", len(plans) == 1, str(len(plans))))
    _, _, first2, resumed2 = run_once(task)  # identical second run in a fresh database
    final2 = resumed2 or first2
    result = TaskResult(task, final, checks, final.fingerprint == final2.fingerprint)
    result.seconds = time.perf_counter() - started
    return result


# --- reporting ---


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def summary_markdown(results: list[TaskResult]) -> str:
    passed = sum(r.passed for r in results)
    total_checks = sum(len(r.checks) for r in results)
    passed_checks = sum(c.passed for r in results for c in r.checks)
    completed_expected = [
        r
        for r in results
        if r.task.expect.status == "completed"
        or (r.task.resume_expect and r.metrics.status == "completed")
    ]
    completion = sum(r.metrics.status == RunStatus.COMPLETED for r in completed_expected)
    decided = sum(r.metrics.supported_claims + r.metrics.contradicted_claims for r in results)
    unsupported = sum(r.metrics.unsupported_claims for r in results)
    report_problems = sum(len(r.metrics.report_check_problems) for r in results)
    errors_handled = [
        r
        for r in results
        if r.task.expect.min_tool_errors
        or r.task.expect.min_tool_blocked
        or r.task.expect.status == "failed"
    ]

    lines = [
        f"**{passed} of {len(results)} tasks passed** ({passed_checks} of {total_checks} checks; "
        f"each task run twice, offline, mock analysis).",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Task completion (tasks meant to complete) | {completion} of "
        f"{len(completed_expected)} |",
        f"| Unsupported-claim rate | {unsupported} of {decided} supported/contradicted claims "
        f"({_pct(unsupported / decided if decided else None)}) |",
        f"| Report evidence-check problems | {report_problems} |",
        f"| Repeatable (identical outcome on rerun) | "
        f"{sum(r.repeatable for r in results)} of {len(results)} |",
        f"| Error scenarios handled as expected | "
        f"{sum(r.passed for r in errors_handled)} of {len(errors_handled)} |",
        "",
        "| Task | Result | Sources | Entity coverage | Cells with evidence | Supported cells "
        "| Claims (S / C / U) | Tool calls (failed / blocked) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m = r.metrics
        result = "pass" if r.passed else "**FAIL**"
        status = (
            m.status if m.status == "completed" else f"{m.status} ({', '.join(m.failed_stages)})"
        )
        cells_cov = f"{_pct(m.cell_evidence_coverage)}" if m.total_cells else "—"
        supported = f"{m.supported_cells} of {m.total_cells}" if m.total_cells else "—"
        lines.append(
            f"| `{r.task.id}` | {result}: {status} | {m.sources} | {_pct(m.entity_coverage)} "
            f"| {cells_cov} | {supported} | {m.supported_claims} / {m.contradicted_claims} / "
            f"{m.unknown_claims} | {m.tool_calls} ({m.tool_errors} / {m.tool_blocked}) |"
        )
    return "\n".join(lines)


def full_markdown(results: list[TaskResult]) -> str:
    out = [
        "# Evaluation results",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`uv run python -m evals.run --update-docs` (backend/). Offline: recorded Wikipedia and "
        "Hacker News responses (2026-11-13), mock analysis, no network or API keys.",
        "",
        summary_markdown(results),
        "",
        "## Tasks and checks",
        "",
    ]
    for r in results:
        out += [f"### `{r.task.id}`: {r.task.title}", "", f"*{r.task.purpose}.*", ""]
        if r.task.documents:
            out.append(f"Uploaded documents: {', '.join(r.task.documents)}.")
        if r.task.settings:
            out.append(f"Settings: {r.task.settings}.")
        out.append("")
        out += [
            f"- {'✅' if c.passed else '❌'} {c.name}" + (f" ({c.detail})" if c.detail else "")
            for c in r.checks
        ]
        out.append(
            f"- {'✅' if r.repeatable else '❌'} identical outcome on a second run "
            f"(fingerprint `{r.metrics.fingerprint}`)"
        )
        out.append("")
    return "\n".join(out)


def update_readme(results: list[TaskResult]) -> None:
    text = README_PATH.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        raise SystemExit(f"README is missing the {README_START} / {README_END} markers")
    head, rest = text.split(README_START, 1)
    _, tail = rest.split(README_END, 1)
    block = f"{README_START}\n{summary_markdown(results)}\n{README_END}"
    README_PATH.write_text(head + block + tail, encoding="utf-8")


def run_all(task_ids: list[str] | None = None) -> list[TaskResult]:
    tasks = [t for t in TASKS if not task_ids or t.id in task_ids]
    if task_ids and len(tasks) != len(set(task_ids)):
        raise SystemExit(f"Unknown task id; choose from: {', '.join(t.id for t in TASKS)}")
    return [evaluate(t) for t in tasks]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline evaluation suite.")
    parser.add_argument("--task", action="append", help="run only this task id (repeatable)")
    parser.add_argument(
        "--update-docs",
        action="store_true",
        help="write docs/evaluation.md, the README summary and results JSON",
    )
    args = parser.parse_args()

    results = run_all(args.task)
    for r in results:
        failed = [c for c in r.checks if not c.passed]
        print(
            f"{'PASS' if r.passed else 'FAIL'}  {r.task.id:<28} {r.seconds:5.2f}s  "
            f"{len(r.checks) - len(failed)}/{len(r.checks)} checks"
            f"{'' if r.repeatable else '  NOT REPEATABLE'}"
        )
        for c in failed:
            print(f"      ✗ {c.name}" + (f" ({c.detail})" if c.detail else ""))
    print()
    print(summary_markdown(results))

    if args.update_docs:
        DOCS_PATH.write_text(full_markdown(results) + "\n", encoding="utf-8")
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(
            json.dumps(
                [
                    {
                        "task": r.task.id,
                        "passed": r.passed,
                        "repeatable": r.repeatable,
                        "checks": [c.__dict__ for c in r.checks],
                        "metrics": r.metrics.as_dict(),
                    }
                    for r in results
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if not args.task:
            update_readme(results)
        print(
            f"\nWrote {DOCS_PATH.relative_to(PROJECT_ROOT)} and "
            f"{RESULTS_PATH.relative_to(PROJECT_ROOT)}"
        )
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

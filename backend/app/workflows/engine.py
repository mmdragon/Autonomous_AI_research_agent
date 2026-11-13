"""Bounded, explicit research workflow: plan → research → analyze → verify → write.

One orchestrator runs the stages in order. Each stage execution is a persisted
ResearchStep; state is saved after every completed stage, so a failed run resumes from
the stage that failed. Limits: steps per run, tool calls per run, sources per question and
per run, and wall-clock time.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.agents.base import Analyst, Planner, Writer
from app.config import Settings
from app.repositories.runs import RunRepository
from app.schemas.research import (
    STAGES,
    ResearchPlan,
    ResearchRequest,
    RunStatus,
    Stage,
    StepStatus,
    ToolQuery,
    VerificationStatus,
    WorkflowState,
)
from app.sources.http import BlockedError, SourceError
from app.sources.models import SourceRecord
from app.sources.registry import SourceTools
from app.verification.verifier import verify_claims

log = logging.getLogger(__name__)


class WorkflowLimitError(Exception):
    """A configured limit stopped the run. The message is safe to show."""


class StageError(Exception):
    """A stage could not produce a usable result. The message is safe to show."""


@dataclass
class Agents:
    planner: Planner
    analyst: Analyst
    writer: Writer


class WorkflowEngine:
    def __init__(
        self,
        repo: RunRepository,
        tools: SourceTools,
        agents: Agents,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repo = repo
        self.tools = tools
        self.agents = agents
        self.settings = settings
        self.clock = clock
        self._deadline = 0.0

    # --- entry points ---

    def run(self, run_id: str) -> RunStatus:
        """Execute a pending run. Returns the final status."""
        if not self.repo.claim_for_execution(run_id, {RunStatus.PENDING}):
            return self.repo.get_summary(run_id).status
        return self._execute(run_id)

    def resume(self, run_id: str) -> RunStatus:
        """Re-run a failed run from its first incomplete stage."""
        if not self.repo.claim_for_execution(run_id, {RunStatus.FAILED}):
            return self.repo.get_summary(run_id).status
        return self._execute(run_id)

    # --- orchestration ---

    def _execute(self, run_id: str) -> RunStatus:
        self._deadline = self.clock() + self.settings.max_run_seconds
        request = self.repo.get_request(run_id)
        state = self.repo.get_state(run_id)
        done = self.repo.completed_stages(run_id)
        stage_fns = {
            Stage.PLAN: self._plan,
            Stage.RESEARCH: self._research,
            Stage.ANALYZE: self._analyze,
            Stage.VERIFY: self._verify,
            Stage.WRITE: self._write,
        }
        for stage in STAGES:
            if stage in done:
                continue
            if self.repo.count_steps(run_id) >= self.settings.max_steps_per_run:
                return self._fail(run_id, f"Step limit reached ({self.settings.max_steps_per_run})")
            step_id = self.repo.start_step(run_id, stage, _input_summary(stage, request, state))
            try:
                self._check_deadline()
                summary = stage_fns[stage](run_id, step_id, request, state)
            except (WorkflowLimitError, StageError, SourceError) as exc:
                self.repo.finish_step(step_id, StepStatus.FAILED, error=str(exc))
                return self._fail(run_id, f"{stage.value} failed: {exc}")
            except Exception as exc:  # never leak internals; keep the run resumable
                log.exception("Stage %s crashed for run %s", stage, run_id)
                message = f"Internal error ({type(exc).__name__})"
                self.repo.finish_step(step_id, StepStatus.FAILED, error=message)
                return self._fail(run_id, f"{stage.value} failed: {message}")
            self.repo.save_state(run_id, state)
            self.repo.finish_step(step_id, StepStatus.COMPLETED, output_summary=summary)
        self.repo.set_status(run_id, RunStatus.COMPLETED)
        return RunStatus.COMPLETED

    def _fail(self, run_id: str, message: str) -> RunStatus:
        self.repo.set_status(run_id, RunStatus.FAILED, message)
        return RunStatus.FAILED

    def _check_deadline(self) -> None:
        if self.clock() > self._deadline:
            raise WorkflowLimitError(f"Run time limit reached ({self.settings.max_run_seconds}s)")

    # --- stages ---

    def _plan(self, run_id, step_id, request: ResearchRequest, state: WorkflowState) -> str:
        plan = self.agents.planner.plan(request)
        if not plan.queries:
            raise StageError("The plan has no source queries")
        state.plan = plan
        return f"{len(plan.questions)} questions, {len(plan.queries)} source queries"

    def _research(self, run_id, step_id, request: ResearchRequest, state: WorkflowState) -> str:
        plan = _require_plan(state)
        cap = min(request.max_sources, self.settings.max_sources_per_run)
        per_query = self.settings.max_sources_per_question
        results: list[list[SourceRecord]] = []
        failures = 0
        for query in plan.queries:
            records = self._run_query(run_id, step_id, query, per_query)
            if records is None:
                failures += 1
            else:
                results.append(records)

        # Round-robin across queries so every entity gets its best result before any
        # query gets a second one.
        stored_ids = list(state.source_ids)
        for rank in range(per_query):
            for records in results:
                if len(stored_ids) >= cap:
                    break
                if rank < len(records):
                    source_id, created = self.repo.add_source(run_id, records[rank])
                    if created:
                        stored_ids.append(source_id)
        state.source_ids = stored_ids
        if not stored_ids:
            raise StageError(
                f"No sources retrieved ({failures} of {len(plan.queries)} queries failed)"
            )
        return (
            f"{len(stored_ids)} sources stored from {len(plan.queries)} queries ({failures} failed)"
        )

    def _run_query(
        self, run_id: str, step_id: str, query: ToolQuery, limit: int
    ) -> list[SourceRecord] | None:
        """Search, then fetch the top result in full. Returns None if the search failed."""
        if query.tool == "user_url":
            record = self._tool_call(
                run_id,
                step_id,
                "user_url.fetch",
                query.query,
                lambda: [self.tools.user_url.fetch(query.query)],
            )
            return record
        source = self.tools.wikipedia if query.tool == "wikipedia" else self.tools.hackernews
        records = self._tool_call(
            run_id,
            step_id,
            f"{query.tool}.search",
            query.query,
            lambda: source.search(query.query, limit),
        )
        if not records:
            return records
        full = self._tool_call(
            run_id,
            step_id,
            f"{query.tool}.fetch",
            records[0].url,
            lambda: [source.fetch(records[0].url)],
        )
        if full:
            records = [full[0], *records[1:]]
        return records

    def _tool_call(
        self,
        run_id: str,
        step_id: str,
        tool: str,
        request: str,
        fn: Callable[[], list[SourceRecord]],
    ) -> list[SourceRecord] | None:
        self._check_deadline()
        if self.repo.count_tool_calls(run_id) >= self.settings.max_tool_calls_per_run:
            raise WorkflowLimitError(
                f"Tool call limit reached ({self.settings.max_tool_calls_per_run})"
            )
        started = datetime.now(UTC).isoformat()
        t0 = time.monotonic()
        requests_before = self.tools.http.request_count
        status, error, result = "ok", None, None
        try:
            result = fn()
        except BlockedError as exc:
            status, error = "blocked", str(exc)
        except SourceError as exc:
            status, error = "error", str(exc)
        self.repo.log_tool_call(
            run_id=run_id,
            step_id=step_id,
            tool=tool,
            request=request,
            status=status,
            result_count=len(result) if result is not None else None,
            error=error,
            http_requests=self.tools.http.request_count - requests_before,
            started_at=started,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        return result

    def _analyze(self, run_id, step_id, request: ResearchRequest, state: WorkflowState) -> str:
        plan = _require_plan(state)
        sources = self.repo.list_sources(run_id)
        claims = self.agents.analyst.analyze(
            request, plan, sources, self.repo.source_contents(run_id)
        )
        self.repo.replace_claims(run_id, claims)
        state.claim_count = len(claims)
        with_evidence = sum(1 for c in claims if c.spans)
        return f"{len(claims)} claims ({with_evidence} with evidence) from {len(sources)} sources"

    def _verify(self, run_id, step_id, request: ResearchRequest, state: WorkflowState) -> str:
        sources = self.repo.list_sources(run_id)
        claims = verify_claims(
            self.repo.list_claims(run_id), sources, self.repo.source_contents(run_id)
        )
        self.repo.replace_claims(run_id, claims)
        counts = {
            s: sum(1 for c in claims if c.verification_status is s) for s in VerificationStatus
        }
        return ", ".join(f"{n} {s.value}" for s, n in counts.items())

    def _write(self, run_id, step_id, request: ResearchRequest, state: WorkflowState) -> str:
        plan = _require_plan(state)
        markdown = self.agents.writer.write(
            request,
            plan,
            self.repo.list_claims(run_id),
            self.repo.list_sources(run_id),
            context={"sources_mode": self.settings.sources_mode},
        )
        state.report_id = self.repo.save_report(run_id, markdown)
        return f"Markdown report, {len(markdown)} characters"


def _require_plan(state: WorkflowState) -> ResearchPlan:
    if state.plan is None:
        raise StageError("No plan in saved state")
    return state.plan


def _input_summary(stage: Stage, request: ResearchRequest, state: WorkflowState) -> str:
    match stage:
        case Stage.PLAN:
            return (
                f"Topic: {request.topic}; {len(request.entities)} entities, "
                f"{len(request.attributes)} attributes, {len(request.questions)} questions"
            )
        case Stage.RESEARCH:
            n = len(state.plan.queries) if state.plan else 0
            return f"{n} queries, up to {request.max_sources} sources"
        case Stage.ANALYZE:
            return f"{len(state.source_ids)} sources"
        case Stage.VERIFY:
            return f"{state.claim_count} claims"
        case Stage.WRITE:
            return "Verified claims and sources"
    return ""

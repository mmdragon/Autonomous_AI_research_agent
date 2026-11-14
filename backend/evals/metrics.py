"""Metrics computed from a finished run's stored data (sources, claims, report, tool calls).

Everything is recomputed from the database, independently of what the stages reported, so the
evaluation checks the stored evidence rather than trusting the workflow's own summaries.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from app.agents.mock import OVERVIEW, cell_status
from app.repositories.runs import RunRepository
from app.schemas.research import Claim, ResearchRequest, StepStatus, VerificationStatus
from app.sources.models import SourceKind
from app.verification.report_check import check_report
from app.verification.sentences import entity_patterns
from app.verification.verifier import verify_claims


@dataclass
class RunMetrics:
    status: str
    error: str | None
    failed_stages: list[str]
    steps: int
    sources: int
    sources_by_kind: dict[str, int]
    entity_coverage: float | None  # entities named in at least one stored source
    cell_evidence_coverage: float | None  # matrix cells with any quoted evidence
    supported_cells: int
    total_cells: int
    claims: int
    supported_claims: int
    contradicted_claims: int
    unknown_claims: int
    conflicts: int
    unsupported_claims: int  # supported/contradicted claims that fail independent re-verification
    unsupported_claim_rate: float | None
    report_saved: bool
    report_check_problems: list[str]
    tool_calls: int
    tool_errors: int
    tool_blocked: int
    http_requests: int
    fingerprint: str  # stable digest of the run's outcome, for repeatability checks

    def as_dict(self) -> dict:
        return asdict(self)


def is_conflict(claim: Claim) -> bool:
    return any(s.stance == "contradicts" for s in claim.spans)


def cells(request: ResearchRequest, claims: list[Claim]) -> dict[tuple[str, str], str]:
    attributes = request.attributes or [OVERVIEW]
    regular = [c for c in claims if not is_conflict(c)]
    return {
        (e, a): cell_status([c for c in regular if c.entity == e and c.attribute == a])
        for e in request.entities
        for a in attributes
    }


def _fingerprint(sources, claims, report: str | None, status: str) -> str:
    """Digest of outcome facts that must not change between identical offline runs."""
    parts = [status]
    parts += sorted(s.url for s in sources)
    parts += sorted(
        f"{c.entity}|{c.attribute}|{c.verification_status}|{c.claim_text}|"
        + ",".join(sorted(sp.quote for sp in c.spans))
        for c in claims
    )
    if report:
        # Drop lines that legitimately vary between runs (generation and retrieval times).
        stable = re.sub(r"^Generated .*$", "", report, flags=re.M)
        parts.append(re.sub(r"retrieved \d{4}-\d{2}-\d{2}", "retrieved <date>", stable))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def compute(repo: RunRepository, run_id: str) -> RunMetrics:
    summary = repo.get_summary(run_id)
    request = repo.get_request(run_id)
    steps = repo.list_steps(run_id)
    sources = repo.list_sources(run_id)
    contents = repo.source_contents(run_id)
    claims = repo.list_claims(run_id)
    report = repo.latest_report(run_id)
    calls = repo.list_tool_calls(run_id)

    kinds: dict[str, int] = {}
    for s in sources:
        kinds[s.source_kind.value] = kinds.get(s.source_kind.value, 0) + 1

    entity_coverage = None
    if request.entities:
        covered = sum(
            1
            for e in request.entities
            if any(p.search(contents.get(s.id, "")) for s in sources for p in entity_patterns(e))
        )
        entity_coverage = covered / len(request.entities)

    grid = cells(request, claims)
    with_evidence = sum(1 for v in grid.values() if v != "unknown")

    # Independent re-verification: every claim the run calls supported or contradicted must
    # still get that status from the verifier, against the stored source text.
    decided = [c for c in claims if c.verification_status is not VerificationStatus.UNKNOWN]
    rechecked = {c.id: c for c in verify_claims(decided, sources, contents)}
    kind_of = {s.id: s.source_kind for s in sources}
    unsupported = 0
    for c in decided:
        again = rechecked[c.id]
        strong = any(
            sp.stance == "supports" and kind_of.get(sp.source_record_id) is not SourceKind.COMMUNITY
            for sp in again.spans
        )
        if again.verification_status is not c.verification_status or not strong:
            unsupported += 1

    status = summary.status.value
    return RunMetrics(
        status=status,
        error=summary.error,
        failed_stages=[s.stage.value for s in steps if s.status is StepStatus.FAILED],
        steps=len(steps),
        sources=len(sources),
        sources_by_kind=kinds,
        entity_coverage=entity_coverage,
        cell_evidence_coverage=with_evidence / len(grid) if grid else None,
        supported_cells=sum(1 for v in grid.values() if v == "supported"),
        total_cells=len(grid),
        claims=len(claims),
        supported_claims=sum(c.verification_status == "supported" for c in claims),
        contradicted_claims=sum(c.verification_status == "contradicted" for c in claims),
        unknown_claims=sum(c.verification_status == "unknown" for c in claims),
        conflicts=sum(1 for c in claims if is_conflict(c)),
        unsupported_claims=unsupported,
        unsupported_claim_rate=unsupported / len(decided) if decided else None,
        report_saved=report is not None,
        report_check_problems=check_report(report.markdown, claims, sources).problems
        if report
        else [],
        tool_calls=len(calls),
        tool_errors=sum(c.status == "error" for c in calls),
        tool_blocked=sum(c.status == "blocked" for c in calls),
        http_requests=sum(c.http_requests for c in calls),
        fingerprint=_fingerprint(sources, claims, report.markdown if report else None, status),
    )

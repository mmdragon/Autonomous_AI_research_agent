"""API and workflow schemas for research runs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
)

from app.sources.models import SourceKind

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Stage(StrEnum):
    PLAN = "plan"
    RESEARCH = "research"
    ANALYZE = "analyze"
    VERIFY = "verify"
    WRITE = "write"


STAGES: tuple[Stage, ...] = tuple(Stage)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class ResearchRequest(BaseModel):
    """What the user asks for. Entities and attributes drive the comparison matrix."""

    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    questions: list[ShortText] = Field(default_factory=list, max_length=5)
    entities: list[Name] = Field(default_factory=list, max_length=8)
    attributes: list[Name] = Field(default_factory=list, max_length=6)
    user_urls: list[AnyHttpUrl] = Field(default_factory=list, max_length=5)
    max_sources: int = Field(default=15, ge=1, le=25)
    output_format: Literal["markdown"] = "markdown"

    @field_validator("entities", "attributes", "questions")
    @classmethod
    def _dedupe(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for v in values:
            if v.casefold() not in seen:
                seen.add(v.casefold())
                out.append(v)
        return out


class ToolQuery(BaseModel):
    tool: Literal["wikipedia", "hackernews", "user_url"]
    query: str  # search text, or the URL for user_url


class ResearchQuestion(BaseModel):
    id: str
    text: str
    entity: str | None = None
    attribute: str | None = None


class ResearchPlan(BaseModel):
    questions: list[ResearchQuestion]
    queries: list[ToolQuery]  # deduplicated tool calls the researcher will make


class WorkflowState(BaseModel):
    """Persisted after each completed stage so a failed run can resume safely."""

    plan: ResearchPlan | None = None
    source_ids: list[str] = Field(default_factory=list)
    claim_count: int = 0
    report_id: str | None = None


class EvidenceSpan(BaseModel):
    id: str
    source_record_id: str
    quote: str
    start: int
    end: int
    stance: Literal["supports", "contradicts"] = "supports"


class Claim(BaseModel):
    id: str
    entity: str | None
    attribute: str | None
    claim_text: str
    claim_type: Literal["fact", "analysis"] = "fact"
    verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    notes: str | None = None
    spans: list[EvidenceSpan] = Field(default_factory=list)

    @computed_field
    @property
    def source_record_ids(self) -> list[str]:
        """Distinct sources this claim's evidence comes from, in span order."""
        return list(dict.fromkeys(s.source_record_id for s in self.spans))


# --- API responses ---


class StepOut(BaseModel):
    id: str
    stage: Stage
    status: StepStatus
    input_summary: str | None
    output_summary: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class ToolCallOut(BaseModel):
    id: str
    step_id: str | None
    tool: str
    request: str
    status: Literal["ok", "error", "blocked"]
    result_count: int | None
    error: str | None
    http_requests: int
    started_at: datetime
    duration_ms: int | None


class SourceOut(BaseModel):
    id: str
    url: str
    title: str
    source_name: str
    source_kind: SourceKind
    retrieved_at: datetime
    published_at: datetime | None
    excerpt: str
    content_hash: str
    license: str | None


class RunSummary(BaseModel):
    id: str
    user_task: str
    status: RunStatus
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class RunDetail(RunSummary):
    request: ResearchRequest
    plan: ResearchPlan | None
    steps: list[StepOut]
    sources: list[SourceOut]
    claims: list[Claim]
    has_report: bool


class ReportOut(BaseModel):
    id: str
    run_id: str
    markdown: str
    created_at: datetime

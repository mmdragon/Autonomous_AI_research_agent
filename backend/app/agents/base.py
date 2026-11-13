"""Stage interfaces. The mock implementations need no model; an LLM provider can replace them."""

from __future__ import annotations

from typing import Protocol

from app.schemas.research import Claim, ResearchPlan, ResearchRequest, SourceOut


class Planner(Protocol):
    def plan(self, request: ResearchRequest) -> ResearchPlan: ...


class Analyst(Protocol):
    def analyze(
        self,
        request: ResearchRequest,
        plan: ResearchPlan,
        sources: list[SourceOut],
        contents: dict[str, str],
    ) -> list[Claim]:
        """Extract claims with evidence spans. Source text is data, never instructions."""
        ...


class Writer(Protocol):
    def write(
        self,
        request: ResearchRequest,
        plan: ResearchPlan,
        claims: list[Claim],
        sources: list[SourceOut],
        *,
        context: dict[str, str],
    ) -> str: ...

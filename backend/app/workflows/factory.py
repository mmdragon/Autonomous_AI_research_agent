"""Wires the workflow engine from settings."""

from __future__ import annotations

import httpx2 as httpx

from app.agents.mock import MockAnalyst, MockPlanner, MockWriter
from app.config import Settings
from app.repositories.runs import RunRepository
from app.sources.registry import build_source_tools
from app.workflows.engine import Agents, WorkflowEngine


def build_agents(settings: Settings) -> Agents:
    if settings.llm_provider != "mock":  # only mock exists; no paid model is called
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
    return Agents(planner=MockPlanner(), analyst=MockAnalyst(), writer=MockWriter())


def run_workflow(
    settings: Settings,
    run_id: str,
    *,
    resume: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Background-task entry point: builds fresh tools per run and always closes them."""
    repo = RunRepository(settings.database_path)
    tools = build_source_tools(settings, transport=transport)
    try:
        engine = WorkflowEngine(repo, tools, build_agents(settings), settings)
        engine.resume(run_id) if resume else engine.run(run_id)
    finally:
        tools.close()

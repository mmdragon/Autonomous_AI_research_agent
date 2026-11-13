from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

from app.config import Settings, get_settings
from app.repositories.runs import RunNotFoundError, RunRepository
from app.schemas.research import (
    ReportOut,
    ResearchRequest,
    RunDetail,
    RunStatus,
    RunSummary,
    ToolCallOut,
)
from app.workflows.factory import run_workflow

router = APIRouter(prefix="/runs", tags=["runs"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_repo(settings: SettingsDep) -> RunRepository:
    return RunRepository(settings.database_path)


RepoDep = Annotated[RunRepository, Depends(get_repo)]


def _detail(repo: RunRepository, run_id: str) -> RunDetail:
    try:
        summary = repo.get_summary(run_id)
    except RunNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from None
    return RunDetail(
        **summary.model_dump(),
        request=repo.get_request(run_id),
        plan=repo.get_state(run_id).plan,
        steps=repo.list_steps(run_id),
        sources=repo.list_sources(run_id),
        claims=repo.list_claims(run_id),
        has_report=repo.latest_report(run_id) is not None,
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_run(
    request: ResearchRequest, background: BackgroundTasks, repo: RepoDep, settings: SettingsDep
) -> RunDetail:
    if missing := repo.missing_documents(request.document_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown document id(s): {', '.join(missing)}"
        )
    run_id = repo.create_run(request)
    background.add_task(run_workflow, settings, run_id)
    return _detail(repo, run_id)


@router.get("")
def list_runs(repo: RepoDep) -> list[RunSummary]:
    return repo.list_runs()


@router.get("/{run_id}")
def get_run(run_id: str, repo: RepoDep) -> RunDetail:
    return _detail(repo, run_id)


@router.get("/{run_id}/tool-calls")
def list_tool_calls(run_id: str, repo: RepoDep) -> list[ToolCallOut]:
    _detail(repo, run_id)
    return repo.list_tool_calls(run_id)


@router.post("/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_run(
    run_id: str, background: BackgroundTasks, repo: RepoDep, settings: SettingsDep
) -> RunDetail:
    detail = _detail(repo, run_id)
    if detail.status is not RunStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed runs can be resumed")
    background.add_task(run_workflow, settings, run_id, resume=True)
    return detail


def _report(repo: RunRepository, run_id: str) -> ReportOut:
    _detail(repo, run_id)
    report = repo.latest_report(run_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not ready")
    return report


@router.get("/{run_id}/report")
def get_report(run_id: str, repo: RepoDep) -> ReportOut:
    return _report(repo, run_id)


@router.get("/{run_id}/report.md")
def download_report(run_id: str, repo: RepoDep) -> Response:
    report = _report(repo, run_id)
    return Response(
        report.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="research-{run_id[:8]}.md"'},
    )

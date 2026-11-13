"""Persistence for research runs, steps, tool calls, sources, claims and reports."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.repositories.db import transaction
from app.schemas.research import (
    Claim,
    DocumentOut,
    EvidenceSpan,
    ReportOut,
    ResearchRequest,
    RunStatus,
    RunSummary,
    SourceOut,
    Stage,
    StepOut,
    StepStatus,
    ToolCallOut,
    VerificationStatus,
    WorkflowState,
)
from app.sources.models import SourceRecord
from app.sources.text import make_excerpt


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return uuid4().hex


class RunNotFoundError(LookupError):
    pass


class RunRepository:
    def __init__(self, database_path: Path) -> None:
        self.path = database_path

    # --- runs ---

    def create_run(self, request: ResearchRequest) -> str:
        run_id = new_id()
        with transaction(self.path) as conn:
            conn.execute(
                "INSERT INTO research_runs (id, user_task, request_json, status, state_json,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    request.topic,
                    request.model_dump_json(),
                    RunStatus.PENDING,
                    WorkflowState().model_dump_json(),
                    now_iso(),
                ),
            )
        return run_id

    def _run_row(self, conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM research_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        return row

    def get_summary(self, run_id: str) -> RunSummary:
        with transaction(self.path) as conn:
            return _summary(self._run_row(conn, run_id))

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM research_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_summary(r) for r in rows]

    def get_request(self, run_id: str) -> ResearchRequest:
        with transaction(self.path) as conn:
            return ResearchRequest.model_validate_json(self._run_row(conn, run_id)["request_json"])

    def get_state(self, run_id: str) -> WorkflowState:
        with transaction(self.path) as conn:
            raw = self._run_row(conn, run_id)["state_json"]
        return WorkflowState.model_validate_json(raw) if raw else WorkflowState()

    def save_state(self, run_id: str, state: WorkflowState) -> None:
        with transaction(self.path) as conn:
            conn.execute(
                "UPDATE research_runs SET state_json = ? WHERE id = ?",
                (state.model_dump_json(), run_id),
            )

    def set_status(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        completed = now_iso() if status in {RunStatus.COMPLETED, RunStatus.FAILED} else None
        with transaction(self.path) as conn:
            conn.execute(
                "UPDATE research_runs SET status = ?, error = ?, completed_at = ? WHERE id = ?",
                (status, error, completed, run_id),
            )

    def claim_for_execution(self, run_id: str, allowed: set[RunStatus]) -> bool:
        """Atomically move a run to RUNNING if it is in an allowed status."""
        marks = ",".join("?" for _ in allowed)
        with transaction(self.path) as conn:
            cur = conn.execute(
                f"UPDATE research_runs SET status = ?, error = NULL, completed_at = NULL"
                f" WHERE id = ? AND status IN ({marks})",
                (RunStatus.RUNNING, run_id, *allowed),
            )
            return cur.rowcount == 1

    def fail_interrupted_runs(self) -> int:
        """Runs left RUNNING by a server restart become FAILED so they can be resumed."""
        with transaction(self.path) as conn:
            conn.execute(
                "UPDATE research_steps SET status = ?, error = ?, completed_at = ?"
                " WHERE status = ?",
                (
                    StepStatus.FAILED,
                    "Interrupted by server restart",
                    now_iso(),
                    StepStatus.RUNNING,
                ),
            )
            cur = conn.execute(
                "UPDATE research_runs SET status = ?, error = ?, completed_at = ?"
                " WHERE status IN (?, ?)",
                (
                    RunStatus.FAILED,
                    "Interrupted by server restart",
                    now_iso(),
                    RunStatus.RUNNING,
                    RunStatus.PENDING,
                ),
            )
            return cur.rowcount

    # --- steps ---

    def start_step(self, run_id: str, stage: Stage, input_summary: str) -> str:
        step_id = new_id()
        with transaction(self.path) as conn:
            conn.execute(
                "INSERT INTO research_steps (id, run_id, stage, status, input_summary,"
                " started_at) VALUES (?, ?, ?, ?, ?, ?)",
                (step_id, run_id, stage, StepStatus.RUNNING, input_summary, now_iso()),
            )
        return step_id

    def finish_step(
        self,
        step_id: str,
        status: StepStatus,
        *,
        output_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        with transaction(self.path) as conn:
            conn.execute(
                "UPDATE research_steps SET status = ?, output_summary = ?, error = ?,"
                " completed_at = ? WHERE id = ?",
                (status, output_summary, error, now_iso(), step_id),
            )

    def list_steps(self, run_id: str) -> list[StepOut]:
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM research_steps WHERE run_id = ? ORDER BY started_at, rowid",
                (run_id,),
            ).fetchall()
        return [StepOut.model_validate(dict(r)) for r in rows]

    def completed_stages(self, run_id: str) -> set[Stage]:
        return {s.stage for s in self.list_steps(run_id) if s.status is StepStatus.COMPLETED}

    def count_steps(self, run_id: str) -> int:
        with transaction(self.path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM research_steps WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

    # --- tool calls ---

    def log_tool_call(
        self,
        *,
        run_id: str,
        step_id: str | None,
        tool: str,
        request: str,
        status: str,
        result_count: int | None,
        error: str | None,
        http_requests: int,
        started_at: str,
        duration_ms: int,
    ) -> None:
        with transaction(self.path) as conn:
            conn.execute(
                "INSERT INTO tool_calls (id, run_id, step_id, tool, request, status,"
                " result_count, error, http_requests, started_at, duration_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id(),
                    run_id,
                    step_id,
                    tool,
                    request,
                    status,
                    result_count,
                    error,
                    http_requests,
                    started_at,
                    duration_ms,
                ),
            )

    def list_tool_calls(self, run_id: str) -> list[ToolCallOut]:
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY started_at, rowid", (run_id,)
            ).fetchall()
        return [ToolCallOut.model_validate(dict(r)) for r in rows]

    def count_tool_calls(self, run_id: str) -> int:
        with transaction(self.path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM tool_calls WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

    # --- sources ---

    def add_source(self, run_id: str, record: SourceRecord) -> tuple[str, bool]:
        """Store a source unless the run already has the same URL or content.

        Returns (stored source id, created).
        """
        with transaction(self.path) as conn:
            existing = conn.execute(
                "SELECT id FROM source_records WHERE run_id = ? AND (url = ? OR content_hash = ?)",
                (run_id, record.url, record.content_hash),
            ).fetchone()
            if existing:
                return existing["id"], False
            conn.execute(
                "INSERT INTO source_records (id, run_id, url, title, source_name, source_kind,"
                " retrieved_at, published_at, excerpt, content_hash, license)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    run_id,
                    record.url,
                    record.title,
                    record.source_name,
                    record.source_kind,
                    record.retrieved_at.isoformat(),
                    record.published_at.isoformat() if record.published_at else None,
                    record.excerpt,
                    record.content_hash,
                    record.license,
                ),
            )
            conn.execute(
                "INSERT INTO source_contents (source_record_id, text) VALUES (?, ?)",
                (record.id, record.content),
            )
        return record.id, True

    def list_sources(self, run_id: str) -> list[SourceOut]:
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM source_records WHERE run_id = ? ORDER BY retrieved_at, rowid",
                (run_id,),
            ).fetchall()
        return [SourceOut.model_validate(dict(r)) for r in rows]

    def source_contents(self, run_id: str) -> dict[str, str]:
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT c.source_record_id, c.text FROM source_contents c"
                " JOIN source_records s ON s.id = c.source_record_id WHERE s.run_id = ?",
                (run_id,),
            ).fetchall()
        return {r["source_record_id"]: r["text"] for r in rows}

    # --- claims ---

    def replace_claims(self, run_id: str, claims: list[Claim]) -> None:
        with transaction(self.path) as conn:
            conn.execute("DELETE FROM claims WHERE run_id = ?", (run_id,))
            for c in claims:
                conn.execute(
                    "INSERT INTO claims (id, run_id, entity, attribute, claim_text, claim_type,"
                    " verification_status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        c.id,
                        run_id,
                        c.entity,
                        c.attribute,
                        c.claim_text,
                        c.claim_type,
                        c.verification_status,
                        c.notes,
                    ),
                )
                for s in c.spans:
                    conn.execute(
                        "INSERT INTO evidence_spans (id, claim_id, source_record_id, quote,"
                        " start_offset, end_offset, stance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (s.id, c.id, s.source_record_id, s.quote, s.start, s.end, s.stance),
                    )

    def list_claims(self, run_id: str) -> list[Claim]:
        with transaction(self.path) as conn:
            claim_rows = conn.execute(
                "SELECT * FROM claims WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
            span_rows = conn.execute(
                "SELECT e.* FROM evidence_spans e JOIN claims c ON c.id = e.claim_id"
                " WHERE c.run_id = ? ORDER BY e.rowid",
                (run_id,),
            ).fetchall()
        spans: dict[str, list[EvidenceSpan]] = {}
        for r in span_rows:
            spans.setdefault(r["claim_id"], []).append(
                EvidenceSpan(
                    id=r["id"],
                    source_record_id=r["source_record_id"],
                    quote=r["quote"],
                    start=r["start_offset"],
                    end=r["end_offset"],
                    stance=r["stance"],
                )
            )
        return [
            Claim(
                id=r["id"],
                entity=r["entity"],
                attribute=r["attribute"],
                claim_text=r["claim_text"],
                claim_type=r["claim_type"],
                verification_status=VerificationStatus(r["verification_status"]),
                notes=r["notes"],
                spans=spans.get(r["id"], []),
            )
            for r in claim_rows
        ]

    # --- documents ---

    def save_document(self, record: SourceRecord, filename: str, data: bytes) -> DocumentOut:
        """Store an uploaded document (already validated). Same bytes → same document."""
        with transaction(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE content_hash = ? AND filename = ?",
                (record.content_hash, filename),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO documents (id, filename, content_hash, size_bytes, data,"
                    " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id(), filename, record.content_hash, len(data), data, now_iso()),
                )
                row = conn.execute(
                    "SELECT * FROM documents WHERE content_hash = ? AND filename = ?",
                    (record.content_hash, filename),
                ).fetchone()
        return _document(row)

    def get_document(self, document_id: str) -> tuple[str, bytes] | None:
        with transaction(self.path) as conn:
            row = conn.execute(
                "SELECT filename, data FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return (row["filename"], bytes(row["data"])) if row else None

    def missing_documents(self, document_ids: list[str]) -> list[str]:
        if not document_ids:
            return []
        marks = ",".join("?" for _ in document_ids)
        with transaction(self.path) as conn:
            found = {
                r["id"]
                for r in conn.execute(
                    f"SELECT id FROM documents WHERE id IN ({marks})", tuple(document_ids)
                )
            }
        return [d for d in document_ids if d not in found]

    # --- reports ---

    def save_report(self, run_id: str, markdown: str) -> str:
        report_id = new_id()
        with transaction(self.path) as conn:
            conn.execute(
                "INSERT INTO reports (id, run_id, markdown, created_at) VALUES (?, ?, ?, ?)",
                (report_id, run_id, markdown, now_iso()),
            )
        return report_id

    def latest_report(self, run_id: str) -> ReportOut | None:
        with transaction(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM reports WHERE run_id = ? ORDER BY created_at DESC, rowid DESC"
                " LIMIT 1",
                (run_id,),
            ).fetchone()
        return ReportOut.model_validate(dict(row)) if row else None


def _document(row: sqlite3.Row) -> DocumentOut:
    text = bytes(row["data"]).decode("utf-8-sig", errors="replace")
    return DocumentOut(
        id=row["id"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        content_hash=row["content_hash"],
        excerpt=make_excerpt(" ".join(text.split()), 200),
        created_at=row["created_at"],
    )


def _summary(row: sqlite3.Row) -> RunSummary:
    return RunSummary(
        id=row["id"],
        user_task=row["user_task"],
        status=RunStatus(row["status"]),
        error=row["error"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )

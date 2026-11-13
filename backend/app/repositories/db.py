"""SQLite setup (stdlib sqlite3). One connection per unit of work."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3

# Timestamps are ISO-8601 UTC strings. JSON-ish fields are stored as TEXT.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    id            TEXT PRIMARY KEY,
    user_task     TEXT NOT NULL,
    request_json  TEXT NOT NULL,          -- topic, questions, source count, output format
    status        TEXT NOT NULL,          -- pending | running | completed | failed
    error         TEXT,
    state_json    TEXT,                   -- WorkflowState, saved after each completed stage
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON research_runs (created_at);

CREATE TABLE IF NOT EXISTS research_steps (
    id             TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    stage          TEXT NOT NULL,         -- plan | research | analyze | verify | write
    status         TEXT NOT NULL,         -- pending | running | completed | failed | skipped
    input_summary  TEXT,
    output_summary TEXT,
    error          TEXT,
    started_at     TEXT,
    completed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON research_steps (run_id);

-- Every external tool call, for the activity log.
CREATE TABLE IF NOT EXISTS tool_calls (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    step_id      TEXT REFERENCES research_steps (id) ON DELETE CASCADE,
    tool         TEXT NOT NULL,
    request      TEXT NOT NULL,
    status       TEXT NOT NULL,           -- ok | error | blocked
    result_count INTEGER,
    error        TEXT,
    http_requests INTEGER NOT NULL DEFAULT 0, -- HTTP requests made, including retries
    started_at   TEXT NOT NULL,
    duration_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls (run_id);

CREATE TABLE IF NOT EXISTS source_records (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    source_name  TEXT NOT NULL,           -- wikipedia | hackernews | user_url | document
    source_kind  TEXT NOT NULL,           -- reference | community | user_url | document
    retrieved_at TEXT NOT NULL,
    published_at TEXT,                    -- only when the source states it; never inferred
    excerpt      TEXT NOT NULL,
    content_hash TEXT NOT NULL,           -- sha256 of normalized text
    license      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_run ON source_records (run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_run_hash ON source_records (run_id, content_hash);

-- Exactly the text that was retrieved, so evidence quotes can be checked against it.
CREATE TABLE IF NOT EXISTS source_contents (
    source_record_id TEXT PRIMARY KEY REFERENCES source_records (id) ON DELETE CASCADE,
    text             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    entity              TEXT,
    attribute           TEXT,
    claim_text          TEXT NOT NULL,
    claim_type          TEXT NOT NULL,    -- fact | analysis
    verification_status TEXT NOT NULL,    -- supported | contradicted | unknown
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims (run_id);

CREATE TABLE IF NOT EXISTS evidence_spans (
    id               TEXT PRIMARY KEY,
    claim_id         TEXT NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    source_record_id TEXT NOT NULL REFERENCES source_records (id) ON DELETE CASCADE,
    quote            TEXT NOT NULL,
    start_offset     INTEGER NOT NULL,
    end_offset       INTEGER NOT NULL,
    stance           TEXT NOT NULL        -- supports | contradicts
);
CREATE INDEX IF NOT EXISTS idx_spans_claim ON evidence_spans (claim_id);

-- User-uploaded documents (text/Markdown), referenced by runs through document_ids.
CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    data         BLOB NOT NULL,           -- original bytes; re-validated when a run loads them
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id         TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    markdown   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_run ON reports (run_id);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path) -> None:
    """Create the database file and tables if missing. Safe to call repeatedly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 1:
            _migrate_v1_to_v2(conn)
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.close()


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE research_runs ADD COLUMN state_json TEXT")
    conn.execute("ALTER TABLE tool_calls RENAME COLUMN attempts TO http_requests")


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection that commits on success and rolls back on error."""
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def check_db(path: Path) -> bool:
    try:
        conn = connect(path)
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            conn.close()
    except sqlite3.Error:
        return False

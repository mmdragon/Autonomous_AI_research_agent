import sqlite3

from app.repositories.db import SCHEMA_VERSION, check_db, init_db, transaction

EXPECTED_TABLES = {
    "research_runs",
    "research_steps",
    "tool_calls",
    "source_records",
    "source_contents",
    "claims",
    "evidence_spans",
    "reports",
}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "database": "ok",
        "llm_provider": "mock",
        "sources_mode": "fixtures",
    }


def test_init_db_creates_schema_and_is_idempotent(tmp_path):
    path = tmp_path / "nested" / "db.sqlite3"
    init_db(path)
    init_db(path)
    with transaction(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert EXPECTED_TABLES <= tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert check_db(path)


def test_check_db_false_for_missing_schema(tmp_path):
    assert not check_db(tmp_path / "empty.sqlite3")


def test_foreign_keys_enforced(tmp_path):
    path = tmp_path / "db.sqlite3"
    init_db(path)
    try:
        with transaction(path) as conn:
            conn.execute(
                "INSERT INTO research_steps (id, run_id, stage, status) VALUES (?, ?, ?, ?)",
                ("s1", "missing-run", "plan", "pending"),
            )
    except sqlite3.IntegrityError:
        return
    raise AssertionError("step without a run should be rejected")


def test_v1_database_is_migrated(tmp_path):
    path = tmp_path / "v1.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE research_runs (id TEXT PRIMARY KEY, user_task TEXT NOT NULL,
            request_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
            created_at TEXT NOT NULL, completed_at TEXT);
        CREATE TABLE tool_calls (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT,
            tool TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL,
            result_count INTEGER, error TEXT, attempts INTEGER NOT NULL DEFAULT 1,
            started_at TEXT NOT NULL, duration_ms INTEGER);
        INSERT INTO research_runs VALUES ('r1', 'old task', '{}', 'completed', NULL, 't', NULL);
        PRAGMA user_version = 1;
        """
    )
    conn.close()
    init_db(path)
    with transaction(path) as conn:
        runs = {r[1] for r in conn.execute("PRAGMA table_info(research_runs)")}
        calls = {r[1] for r in conn.execute("PRAGMA table_info(tool_calls)")}
        assert conn.execute("SELECT user_task FROM research_runs").fetchone()[0] == "old task"
    assert "state_json" in runs
    assert "http_requests" in calls and "attempts" not in calls
    assert check_db(path)

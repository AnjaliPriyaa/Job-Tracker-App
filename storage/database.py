"""SQLite database setup and connection management."""

import sqlite3
from pathlib import Path
from threading import local

_DB_PATH = Path(__file__).resolve().parent.parent / "job_tracker.db"
_thread_local = local()


def get_db() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = sqlite3.connect(str(_DB_PATH))
        _thread_local.conn.row_factory = sqlite3.Row
        _thread_local.conn.execute("PRAGMA journal_mode=WAL")
        _thread_local.conn.execute("PRAGMA foreign_keys=ON")
    return _thread_local.conn


def init_db() -> None:
    """Create tables if they don't exist."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            canonical_id TEXT PRIMARY KEY,
            company_normalized TEXT NOT NULL DEFAULT '',
            title_normalized TEXT NOT NULL DEFAULT '',
            location_normalized TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'discovered',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS job_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL REFERENCES jobs(canonical_id),
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            company TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            UNIQUE(source, source_job_id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL REFERENCES jobs(canonical_id),
            decision TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0.0,
            confidence REAL NOT NULL DEFAULT 0.0,
            reasons TEXT NOT NULL DEFAULT '[]',
            missing_info TEXT NOT NULL DEFAULT '[]',
            investigation_depth INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL REFERENCES jobs(canonical_id),
            sent_at TEXT NOT NULL,
            telegram_message_id TEXT DEFAULT '',
            success INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            tool_calls INTEGER NOT NULL DEFAULT 0,
            searches INTEGER NOT NULL DEFAULT 0,
            notifications_sent INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running'
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_companies ON jobs(company_normalized);
        CREATE INDEX IF NOT EXISTS idx_sources_canonical ON job_sources(canonical_id);
        CREATE INDEX IF NOT EXISTS idx_sources_dedup ON job_sources(source, source_job_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_job ON notifications(canonical_id);
    """)
    db.commit()

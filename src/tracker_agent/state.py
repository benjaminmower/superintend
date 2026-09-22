"""SQLite state: row snapshots, run log, doc chunks (FTS5)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS row_snapshots (
    tab TEXT NOT NULL,
    row_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (tab, row_key)
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms REAL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    doc_name,
    location,
    text,
    tokenize = 'porter'
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def log_run(
    conn: sqlite3.Connection,
    *,
    command: str,
    status: str,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: float | None = None,
    detail: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO run_log
            (command, model, input_tokens, output_tokens, latency_ms, status, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (command, model, input_tokens, output_tokens, latency_ms, status, detail, time.time()),
    )
    conn.commit()

"""SQLite state: run log, parsed weekly-tab history, doc/history chunks (FTS5).

No row-snapshot table: the sheet's own change log gives history for free
(see CLAUDE.md's "Sheet quirks to respect"), so no snapshot-diffing is
needed here.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "tracker.db"

SCHEMA = """
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

-- One row per (project, tab, sub, item) parsed from a weekly tab; a cache
-- so RAG ingest and backtest don't have to re-parse every tab every run.
CREATE TABLE IF NOT EXISTS parsed_items (
    project_id TEXT NOT NULL,
    tab TEXT NOT NULL,
    sub TEXT NOT NULL,
    item TEXT NOT NULL,
    date TEXT,
    status TEXT NOT NULL,
    details TEXT NOT NULL,
    notes TEXT NOT NULL,
    row INTEGER NOT NULL,
    parsed_at REAL NOT NULL,
    PRIMARY KEY (project_id, tab, sub, item)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    project_id,
    source,        -- doc name, or "tracker"
    location,      -- page/section for docs; tab/week for tracker history
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

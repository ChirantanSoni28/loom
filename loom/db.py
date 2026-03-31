"""SQLite schema initialization and connection helper for ~/.loom/index.db."""

import sqlite3
from pathlib import Path

from loom.config import LOOM_DIR

DB_PATH = LOOM_DIR / "index.db"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sync_state (
    path        TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    indexed_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_writes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_path  TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_cache (
    from_path   TEXT NOT NULL,
    to_path     TEXT NOT NULL,
    PRIMARY KEY (from_path, to_path)
);

CREATE TABLE IF NOT EXISTS pending_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    tool_input    TEXT NOT NULL,
    tool_response TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-chunk tracking: stable content-addressed IDs allow skipping unchanged
-- chunks during incremental reindex without re-embedding the whole note.
CREATE TABLE IF NOT EXISTS chunk_state (
    chunk_id   TEXT PRIMARY KEY,
    note_path  TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    indexed_at TIMESTAMP NOT NULL
);

-- Mean-pooled representative embedding per note (average of chunk vectors).
-- Stored as a raw BLOB of IEEE 754 doubles for fast pairwise similarity in
-- the semantic link discovery engine.
CREATE TABLE IF NOT EXISTS note_embeddings (
    note_path  TEXT PRIMARY KEY,
    embedding  BLOB NOT NULL,
    indexed_at TIMESTAMP NOT NULL
);

-- Pending semantic link suggestions awaiting user review.
-- source_path and target_path are vault-relative note paths.
-- status: 'pending' | 'approved' | 'rejected'
CREATE TABLE IF NOT EXISTS pending_links (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path    TEXT NOT NULL,
    target_path    TEXT NOT NULL,
    similarity     REAL NOT NULL,
    source_excerpt TEXT,
    target_excerpt TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_path, target_path)
);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the Loom SQLite database and ensure schema exists."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    return conn


def init_db(db_path: Path | None = None) -> Path:
    """Initialize the database and return its path."""
    path = db_path or DB_PATH
    conn = get_connection(path)
    conn.close()
    return path

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

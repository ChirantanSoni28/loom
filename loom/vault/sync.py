"""Offline write queue — buffers vault writes to SQLite when Obsidian is closed."""

import sqlite3

from obsidian_mcp import ObsidianCLI


async def queue_write(db: sqlite3.Connection, vault_path: str, content: str) -> None:
    """Queue a write operation for later flush when Obsidian reconnects."""
    db.execute(
        "INSERT INTO pending_writes (vault_path, content) VALUES (?, ?)",
        (vault_path, content),
    )
    db.commit()


async def flush_writes(cli: ObsidianCLI, db: sqlite3.Connection) -> int:
    """Replay all queued writes via the Obsidian CLI in creation order.

    Returns the number of writes flushed.
    """
    cursor = db.execute(
        "SELECT id, vault_path, content FROM pending_writes ORDER BY created_at ASC"
    )
    rows = cursor.fetchall()

    flushed = 0
    for row_id, vault_path, content in rows:
        await cli.write_note(vault_path, content)
        db.execute("DELETE FROM pending_writes WHERE id = ?", (row_id,))
        db.commit()
        flushed += 1

    return flushed


def pending_count(db: sqlite3.Connection) -> int:
    """Return the number of pending writes in the queue."""
    cursor = db.execute("SELECT COUNT(*) FROM pending_writes")
    return cursor.fetchone()[0]

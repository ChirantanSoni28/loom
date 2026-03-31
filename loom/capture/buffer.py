"""SQLite-backed event buffer for capturing tool events during a session."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from loom.capture.classifier import EventType, classify_event
from loom.db import get_connection


@dataclass
class BufferedEvent:
    """A classified tool event stored in the buffer."""

    id: int
    session_id: str
    event_type: EventType
    tool_name: str
    tool_input: dict
    tool_response: dict
    created_at: str


def buffer_event(
    session_id: str,
    tool_name: str,
    tool_input: dict,
    tool_response: dict,
    db_path: None = None,
) -> EventType:
    """Classify and buffer a tool event.

    Returns the classified EventType. Events classified as 'skip'
    are not persisted.

    Args:
        session_id: Unique identifier for the current session.
        tool_name: Name of the tool that was used.
        tool_input: Input parameters passed to the tool.
        tool_response: Response returned by the tool.
        db_path: Optional override for the database path (testing).

    Returns:
        The EventType assigned to this event.
    """
    event_type = classify_event(tool_name, tool_input, tool_response)

    if event_type == "skip":
        return event_type

    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO pending_events
               (session_id, event_type, tool_name, tool_input, tool_response, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                event_type,
                tool_name,
                json.dumps(tool_input),
                json.dumps(tool_response),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return event_type


def load_events(
    session_id: str,
    db_path: None = None,
) -> list[BufferedEvent]:
    """Load all buffered events for a session, ordered by creation time.

    Args:
        session_id: The session to load events for.
        db_path: Optional override for the database path (testing).

    Returns:
        List of BufferedEvent instances in chronological order.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """SELECT id, session_id, event_type, tool_name, tool_input, tool_response, created_at
               FROM pending_events
               WHERE session_id = ?
               ORDER BY created_at ASC""",
            (session_id,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        BufferedEvent(
            id=row[0],
            session_id=row[1],
            event_type=row[2],
            tool_name=row[3],
            tool_input=json.loads(row[4]),
            tool_response=json.loads(row[5]),
            created_at=row[6],
        )
        for row in rows
    ]


def clear_events(
    session_id: str,
    db_path: None = None,
) -> int:
    """Delete all buffered events for a session.

    Args:
        session_id: The session whose events should be cleared.
        db_path: Optional override for the database path (testing).

    Returns:
        Number of events deleted.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM pending_events WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        deleted = cursor.rowcount
    finally:
        conn.close()

    return deleted

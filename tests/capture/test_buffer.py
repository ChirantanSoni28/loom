"""Tests for loom.capture.buffer — SQLite-backed event buffer."""

import pytest

from loom.capture.buffer import BufferedEvent, buffer_event, clear_events, load_events
from loom.db import get_connection


@pytest.fixture()
def db_path(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
def _patch_db(db_path, monkeypatch):
    """Patch get_connection to use temporary database."""
    original_get_connection = get_connection

    def patched_get_connection(path=None):
        return original_get_connection(db_path)

    monkeypatch.setattr("loom.capture.buffer.get_connection", patched_get_connection)


class TestBufferEvent:
    """Test buffer_event: classify + persist."""

    def test_file_edit_is_buffered(self) -> None:
        result = buffer_event(
            "session-1", "Write",
            {"file_path": "/foo.py", "content": "x"},
            {"success": True},
        )
        assert result == "file_edit"

        events = load_events("session-1")
        assert len(events) == 1
        assert events[0].event_type == "file_edit"
        assert events[0].tool_name == "Write"

    def test_skip_events_not_persisted(self) -> None:
        result = buffer_event(
            "session-1", "Read",
            {"file_path": "/foo.py"},
            {"content": "..."},
        )
        assert result == "skip"

        events = load_events("session-1")
        assert len(events) == 0

    def test_bash_command_is_buffered(self) -> None:
        result = buffer_event(
            "session-1", "Bash",
            {"command": "pytest --tb=short"},
            {"exit_code": 0},
        )
        assert result == "bash_command"

        events = load_events("session-1")
        assert len(events) == 1
        assert events[0].event_type == "bash_command"

    def test_decision_signal_is_buffered(self) -> None:
        result = buffer_event(
            "session-1", "Write",
            {"file_path": "/foo.py", "content": "We decided to use X because Y"},
            {"success": True},
        )
        assert result == "decision_signal"

        events = load_events("session-1")
        assert len(events) == 1
        assert events[0].event_type == "decision_signal"

    def test_multiple_events_buffered(self) -> None:
        buffer_event("s1", "Write", {"file_path": "/a.py", "content": "x"}, {"success": True})
        buffer_event("s1", "Bash", {"command": "pytest"}, {"exit_code": 0})
        buffer_event("s1", "Read", {"file_path": "/b.py"}, {"content": "y"})  # skip

        events = load_events("s1")
        assert len(events) == 2

    def test_events_isolated_by_session(self) -> None:
        buffer_event("s1", "Write", {"file_path": "/a.py", "content": "x"}, {"success": True})
        buffer_event("s2", "Write", {"file_path": "/b.py", "content": "y"}, {"success": True})

        assert len(load_events("s1")) == 1
        assert len(load_events("s2")) == 1


class TestLoadEvents:
    """Test load_events ordering and structure."""

    def test_events_ordered_chronologically(self) -> None:
        buffer_event("s1", "Write", {"file_path": "/a.py", "content": "x"}, {"success": True})
        buffer_event("s1", "Write", {"file_path": "/b.py", "content": "y"}, {"success": True})

        events = load_events("s1")
        assert events[0].tool_input["file_path"] == "/a.py"
        assert events[1].tool_input["file_path"] == "/b.py"

    def test_empty_session_returns_empty_list(self) -> None:
        events = load_events("nonexistent")
        assert events == []

    def test_buffered_event_has_correct_fields(self) -> None:
        buffer_event("s1", "Edit", {"file_path": "/x.py", "old_string": "a", "new_string": "b"}, {"success": True})

        events = load_events("s1")
        event = events[0]
        assert isinstance(event, BufferedEvent)
        assert event.session_id == "s1"
        assert event.event_type == "file_edit"
        assert event.tool_name == "Edit"
        assert event.tool_input["file_path"] == "/x.py"
        assert event.created_at  # non-empty


class TestClearEvents:
    """Test clear_events."""

    def test_clear_removes_all_session_events(self) -> None:
        buffer_event("s1", "Write", {"file_path": "/a.py", "content": "x"}, {"success": True})
        buffer_event("s1", "Bash", {"command": "pytest"}, {"exit_code": 0})

        deleted = clear_events("s1")
        assert deleted == 2
        assert load_events("s1") == []

    def test_clear_only_affects_target_session(self) -> None:
        buffer_event("s1", "Write", {"file_path": "/a.py", "content": "x"}, {"success": True})
        buffer_event("s2", "Write", {"file_path": "/b.py", "content": "y"}, {"success": True})

        clear_events("s1")
        assert len(load_events("s1")) == 0
        assert len(load_events("s2")) == 1

    def test_clear_nonexistent_session_returns_zero(self) -> None:
        deleted = clear_events("nonexistent")
        assert deleted == 0

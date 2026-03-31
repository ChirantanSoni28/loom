"""Tests for loom.capture.note_builder — session note assembly."""

import pytest

from loom.capture.buffer import BufferedEvent
from loom.capture.note_builder import build_session_note, extract_decisions


def _make_event(
    event_type: str = "file_edit",
    tool_name: str = "Write",
    tool_input: dict | None = None,
    tool_response: dict | None = None,
    session_id: str = "s1",
) -> BufferedEvent:
    """Helper to create a BufferedEvent for testing."""
    return BufferedEvent(
        id=1,
        session_id=session_id,
        event_type=event_type,
        tool_name=tool_name,
        tool_input=tool_input or {},
        tool_response=tool_response or {},
        created_at="2026-03-30T12:00:00+00:00",
    )


class TestBuildSessionNote:
    """Test build_session_note output structure."""

    def test_contains_frontmatter(self) -> None:
        events = [_make_event(tool_input={"file_path": "/a.py", "content": "x"})]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert note.startswith("---\n")
        assert "type: session" in note
        assert "project: my-repo" in note
        assert "date: 2026-03-30" in note

    def test_contains_title(self) -> None:
        events = [_make_event(tool_input={"file_path": "/a.py", "content": "x"})]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "# Session: 2026-03-30" in note

    def test_contains_summary(self) -> None:
        events = [_make_event(tool_input={"file_path": "/a.py", "content": "x"})]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "## Summary" in note
        assert "1 file changed" in note

    def test_files_changed_section(self) -> None:
        events = [
            _make_event(tool_input={"file_path": "/a.py", "content": "x"}),
            _make_event(tool_input={"file_path": "/b.py", "content": "y"}),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "## Files Changed" in note
        assert "- `/a.py`" in note
        assert "- `/b.py`" in note

    def test_files_are_deduplicated(self) -> None:
        events = [
            _make_event(tool_input={"file_path": "/a.py", "content": "x"}),
            _make_event(tool_input={"file_path": "/a.py", "content": "y"}),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert note.count("- `/a.py`") == 1

    def test_bash_commands_section(self) -> None:
        events = [
            _make_event(
                event_type="bash_command",
                tool_name="Bash",
                tool_input={"command": "pytest --tb=short"},
            ),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "## Commands Run" in note
        assert "pytest --tb=short" in note

    def test_decisions_section(self) -> None:
        events = [
            _make_event(
                event_type="decision_signal",
                tool_name="Write",
                tool_input={"file_path": "/config.py", "content": "We decided to use SQLite"},
            ),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "## Key Decisions" in note

    def test_empty_events_produces_no_activity(self) -> None:
        note = build_session_note([], "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "No significant activity captured" in note

    def test_no_files_changed_section_when_no_edits(self) -> None:
        events = [
            _make_event(
                event_type="bash_command",
                tool_name="Bash",
                tool_input={"command": "git status"},
            ),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "## Files Changed" not in note

    def test_long_bash_command_truncated(self) -> None:
        long_cmd = "x" * 200
        events = [
            _make_event(
                event_type="bash_command",
                tool_name="Bash",
                tool_input={"command": long_cmd},
            ),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "..." in note
        # Should not contain the full 200-char command
        assert long_cmd not in note

    def test_error_resolution_section(self) -> None:
        events = [
            _make_event(
                event_type="error_resolution",
                tool_name="Bash",
                tool_input={"command": "npm install"},
                tool_response={"output": "Fixed missing dependency"},
            ),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "## Errors Resolved" in note

    def test_summary_counts_are_correct(self) -> None:
        events = [
            _make_event(tool_input={"file_path": "/a.py", "content": "x"}),
            _make_event(tool_input={"file_path": "/b.py", "content": "y"}),
            _make_event(event_type="bash_command", tool_name="Bash", tool_input={"command": "pytest"}),
            _make_event(event_type="decision_signal", tool_name="Write", tool_input={"content": "decided"}),
        ]
        note = build_session_note(events, "my-repo", "2026-03-30", "/workspace/my-repo")
        assert "2 files changed" in note
        assert "1 decision made" in note
        assert "1 command run" in note


class TestExtractDecisions:
    """Test extract_decisions for standalone decision notes."""

    def test_extracts_decision_events(self) -> None:
        events = [
            _make_event(
                event_type="decision_signal",
                tool_name="Write",
                tool_input={"file_path": "/config.py", "content": "Decided on SQLite"},
            ),
            _make_event(tool_input={"file_path": "/a.py", "content": "x"}),  # file_edit, not a decision
        ]
        decisions = extract_decisions(events)
        assert len(decisions) == 1
        assert "title" in decisions[0]
        assert "content" in decisions[0]

    def test_no_decisions_returns_empty(self) -> None:
        events = [_make_event(tool_input={"file_path": "/a.py", "content": "x"})]
        decisions = extract_decisions(events)
        assert decisions == []

    def test_decision_content_includes_tool_info(self) -> None:
        events = [
            _make_event(
                event_type="decision_signal",
                tool_name="Bash",
                tool_input={"command": "npm install express"},
                tool_response={"output": "installed"},
            ),
        ]
        decisions = extract_decisions(events)
        assert "Bash" in decisions[0]["content"]

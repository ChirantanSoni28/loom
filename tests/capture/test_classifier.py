"""Tests for loom.capture.classifier — event classification logic."""

import pytest

from loom.capture.classifier import EventType, classify_event


class TestClassifyEvent:
    """Test classify_event for each EventType."""

    # --- skip ---

    def test_read_tool_is_skipped(self) -> None:
        result = classify_event("Read", {"file_path": "/foo.py"}, {"content": "..."})
        assert result == "skip"

    def test_glob_tool_is_skipped(self) -> None:
        result = classify_event("Glob", {"pattern": "*.py"}, {"files": []})
        assert result == "skip"

    def test_grep_tool_is_skipped(self) -> None:
        result = classify_event("Grep", {"pattern": "foo"}, {"matches": []})
        assert result == "skip"

    def test_todo_read_is_skipped(self) -> None:
        result = classify_event("TodoRead", {}, {"items": []})
        assert result == "skip"

    def test_task_list_is_skipped(self) -> None:
        result = classify_event("TaskList", {}, {"tasks": []})
        assert result == "skip"

    def test_unknown_tool_is_skipped(self) -> None:
        result = classify_event("SomeUnknownTool", {}, {})
        assert result == "skip"

    # --- file_edit ---

    def test_write_tool_is_file_edit(self) -> None:
        result = classify_event("Write", {"file_path": "/foo.py", "content": "x"}, {"success": True})
        assert result == "file_edit"

    def test_edit_tool_is_file_edit(self) -> None:
        result = classify_event("Edit", {"file_path": "/foo.py", "old_string": "a", "new_string": "b"}, {"success": True})
        assert result == "file_edit"

    def test_notebook_edit_is_file_edit(self) -> None:
        result = classify_event("NotebookEdit", {"path": "/nb.ipynb"}, {"success": True})
        assert result == "file_edit"

    # --- bash_command ---

    def test_bash_nontrivial_is_bash_command(self) -> None:
        result = classify_event("Bash", {"command": "pytest --tb=short"}, {"exit_code": 0})
        assert result == "bash_command"

    def test_bash_git_is_bash_command(self) -> None:
        result = classify_event("Bash", {"command": "git status"}, {"output": "..."})
        assert result == "bash_command"

    def test_bash_trivial_ls_is_skipped(self) -> None:
        result = classify_event("Bash", {"command": "ls -la"}, {"output": "..."})
        assert result == "skip"

    def test_bash_trivial_pwd_is_skipped(self) -> None:
        result = classify_event("Bash", {"command": "pwd"}, {"output": "/home/user"})
        assert result == "skip"

    def test_bash_trivial_echo_is_skipped(self) -> None:
        result = classify_event("Bash", {"command": "echo hello"}, {"output": "hello"})
        assert result == "skip"

    def test_bash_empty_command_is_skipped(self) -> None:
        result = classify_event("Bash", {"command": ""}, {})
        assert result == "skip"

    # --- decision_signal ---

    def test_decision_keyword_in_input(self) -> None:
        result = classify_event(
            "Write",
            {"file_path": "/foo.py", "content": "We decided to use SQLite instead of Postgres"},
            {"success": True},
        )
        assert result == "decision_signal"

    def test_decision_keyword_chose_in_input(self) -> None:
        result = classify_event(
            "Edit",
            {"file_path": "/foo.py", "old_string": "x", "new_string": "We chose async over sync because performance"},
            {"success": True},
        )
        assert result == "decision_signal"

    def test_decision_keyword_tradeoff_in_response(self) -> None:
        result = classify_event(
            "Bash",
            {"command": "npm install express"},
            {"output": "This is a trade-off between speed and simplicity"},
        )
        assert result == "decision_signal"

    def test_decision_keyword_in_bash_input(self) -> None:
        result = classify_event(
            "Bash",
            {"command": "# opted for pip over uv because compatibility"},
            {"exit_code": 0},
        )
        assert result == "decision_signal"

    def test_no_decision_keyword_regular_edit(self) -> None:
        result = classify_event(
            "Write",
            {"file_path": "/foo.py", "content": "def hello(): pass"},
            {"success": True},
        )
        assert result == "file_edit"

    # --- decision_signal overrides other types ---

    def test_decision_signal_overrides_file_edit(self) -> None:
        """Decision keywords take priority over file_edit classification."""
        result = classify_event(
            "Write",
            {"file_path": "/foo.py", "content": "We preferred this approach because of X"},
            {"success": True},
        )
        assert result == "decision_signal"

    def test_decision_signal_overrides_bash(self) -> None:
        """Decision keywords take priority over bash_command classification."""
        result = classify_event(
            "Bash",
            {"command": "We went with option A"},
            {"exit_code": 0},
        )
        assert result == "decision_signal"

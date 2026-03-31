"""Tests for loom.compression.extractor — decision and pattern extraction."""

import pytest

from loom.compression.extractor import (
    _extract_files_changed,
    _parse_decisions_section,
    _slugify,
)


class TestParseDecisionsSection:
    """Test parsing Key Decisions from session notes."""

    def test_extracts_decisions(self) -> None:
        content = (
            "## Summary\n\nSome work.\n\n"
            "## Key Decisions\n\n"
            "- **Use SQLite**: Because it's simple and local\n"
            "- **Async first**: For better performance\n\n"
            "## Files Changed\n\n- `foo.py`\n"
        )
        decisions = _parse_decisions_section(content)
        assert len(decisions) == 2
        assert decisions[0][0] == "Use SQLite"
        assert "simple and local" in decisions[0][1]

    def test_no_decisions_section(self) -> None:
        content = "## Summary\n\nJust some work.\n\n## Files Changed\n\n- `foo.py`\n"
        decisions = _parse_decisions_section(content)
        assert decisions == []

    def test_empty_decisions_section(self) -> None:
        content = "## Key Decisions\n\n## Files Changed\n\n- `foo.py`\n"
        decisions = _parse_decisions_section(content)
        assert decisions == []


class TestExtractFilesChanged:
    """Test parsing Files Changed from session notes."""

    def test_extracts_files(self) -> None:
        content = (
            "## Files Changed\n\n"
            "- `/src/main.py`\n"
            "- `/src/config.py`\n\n"
            "## Commands Run\n\n- `pytest`\n"
        )
        files = _extract_files_changed(content)
        assert len(files) == 2
        assert "/src/main.py" in files
        assert "/src/config.py" in files

    def test_no_files_section(self) -> None:
        content = "## Summary\n\nSome work.\n"
        files = _extract_files_changed(content)
        assert files == []


class TestSlugify:
    """Test slug generation."""

    def test_basic_slug(self) -> None:
        assert _slugify("Use SQLite") == "use-sqlite"

    def test_special_chars_removed(self) -> None:
        assert _slugify("What's the plan?") == "whats-the-plan"

    def test_truncated_at_80(self) -> None:
        long = "a" * 100
        assert len(_slugify(long)) <= 80

    def test_no_double_hyphens(self) -> None:
        result = _slugify("hello   world")
        assert "--" not in result

"""Tests for loom.compression.scheduler — compression checks and reporting."""

import pytest
from datetime import UTC, datetime

from loom.compression.scheduler import CompressionReport, _current_quarter, _note_age_days
from loom.config import LoomConfig


class TestCompressionReport:
    """Test CompressionReport dataclass."""

    def test_defaults(self) -> None:
        report = CompressionReport(project="test")
        assert report.hot_ready == []
        assert report.warm_ready == []
        assert report.can_compress is False
        assert report.requires_approval is True

    def test_with_ready_sessions(self) -> None:
        report = CompressionReport(
            project="test",
            hot_ready=["a.md", "b.md"],
            can_compress=True,
        )
        assert len(report.hot_ready) == 2
        assert report.can_compress is True


class TestCurrentQuarter:
    """Test quarter string generation."""

    def test_format(self) -> None:
        q = _current_quarter()
        assert q.startswith("20")
        assert "-Q" in q
        assert q[-1] in "1234"


class TestNoteAgeCalculation:
    """Test note age determination from frontmatter."""

    @pytest.mark.asyncio
    async def test_age_from_date_frontmatter(self) -> None:
        from unittest.mock import AsyncMock

        client = AsyncMock()
        client.read_note.return_value = "---\ndate: 2026-03-20\n---\n\nContent"

        now = datetime(2026, 3, 30, tzinfo=UTC)
        age = await _note_age_days("test.md", client, now)
        assert age == 10

    @pytest.mark.asyncio
    async def test_age_from_created_frontmatter(self) -> None:
        from unittest.mock import AsyncMock

        client = AsyncMock()
        client.read_note.return_value = "---\ncreated: 2026-03-25T00:00:00Z\n---\n\nContent"

        now = datetime(2026, 3, 30, tzinfo=UTC)
        age = await _note_age_days("test.md", client, now)
        assert age == 5

    @pytest.mark.asyncio
    async def test_age_from_filename(self) -> None:
        from unittest.mock import AsyncMock

        client = AsyncMock()
        client.read_note.return_value = "---\ntype: session\n---\n\nContent"

        now = datetime(2026, 3, 30, tzinfo=UTC)
        age = await _note_age_days("sessions/hot/2026-03-28.md", client, now)
        assert age == 2

    @pytest.mark.asyncio
    async def test_age_returns_none_on_error(self) -> None:
        from unittest.mock import AsyncMock

        client = AsyncMock()
        client.read_note.side_effect = FileNotFoundError

        now = datetime(2026, 3, 30, tzinfo=UTC)
        age = await _note_age_days("nonexistent.md", client, now)
        assert age is None

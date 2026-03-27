"""Tests for loom.vault.sync — offline write queue."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from loom.db import get_connection
from loom.vault.sync import flush_writes, pending_count, queue_write


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    return get_connection(tmp_path / "test.db")


class TestQueueWrite:
    async def test_queues_single(self, db: sqlite3.Connection) -> None:
        await queue_write(db, "projects/note.md", "# Hello")
        assert pending_count(db) == 1

    async def test_queues_multiple(self, db: sqlite3.Connection) -> None:
        await queue_write(db, "note1.md", "content1")
        await queue_write(db, "note2.md", "content2")
        assert pending_count(db) == 2


class TestFlushWrites:
    async def test_flushes_in_order(self, db: sqlite3.Connection) -> None:
        await queue_write(db, "note1.md", "first")
        await queue_write(db, "note2.md", "second")

        mock_rest = AsyncMock()
        mock_rest.write_note = AsyncMock()

        flushed = await flush_writes(mock_rest, db)

        assert flushed == 2
        assert pending_count(db) == 0
        calls = mock_rest.write_note.call_args_list
        assert calls[0].args == ("note1.md", "first")
        assert calls[1].args == ("note2.md", "second")

    async def test_flush_empty_queue(self, db: sqlite3.Connection) -> None:
        mock_rest = AsyncMock()
        flushed = await flush_writes(mock_rest, db)
        assert flushed == 0


class TestPendingCount:
    async def test_zero_initially(self, db: sqlite3.Connection) -> None:
        assert pending_count(db) == 0

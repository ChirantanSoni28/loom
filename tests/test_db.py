"""Tests for loom.db — SQLite schema initialization and connection."""

from pathlib import Path

from loom.db import get_connection, init_db


class TestGetConnection:
    def test_creates_tables(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "graph_cache" in tables
        assert "pending_writes" in tables
        assert "sync_state" in tables

    def test_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn1 = get_connection(db_path)
        conn1.close()
        # Second call should not raise
        conn2 = get_connection(db_path)
        conn2.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "deep" / "test.db"
        conn = get_connection(db_path)
        conn.close()
        assert db_path.exists()

    def test_pending_writes_schema(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        conn.execute(
            "INSERT INTO pending_writes (vault_path, content) VALUES (?, ?)",
            ("test/note.md", "# Hello"),
        )
        row = conn.execute("SELECT vault_path, content FROM pending_writes").fetchone()
        conn.close()
        assert row == ("test/note.md", "# Hello")


class TestInitDb:
    def test_returns_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        result = init_db(db_path)
        assert result == db_path
        assert db_path.exists()

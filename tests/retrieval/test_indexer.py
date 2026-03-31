"""Tests for loom.retrieval.indexer — vault indexing pipeline."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.config import LoomConfig
from loom.retrieval.indexer import (
    IndexReport,
    _content_hash,
    _get_stored_hash,
    _scan_vault,
    _update_hash,
)
from loom.db import get_connection


class TestContentHash:
    """Test content hashing for change detection."""

    def test_hash_is_deterministic(self) -> None:
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_content_different_hash(self) -> None:
        assert _content_hash("hello") != _content_hash("world")

    def test_hash_is_sha256(self) -> None:
        expected = hashlib.sha256(b"test").hexdigest()
        assert _content_hash("test") == expected


class TestSyncState:
    """Test sync_state database operations."""

    @pytest.fixture()
    def db(self, tmp_path):
        return get_connection(tmp_path / "test.db")

    def test_no_stored_hash_returns_none(self, db) -> None:
        assert _get_stored_hash(db, "nonexistent.md") is None

    def test_update_and_retrieve_hash(self, db) -> None:
        _update_hash(db, "note.md", "abc123")
        assert _get_stored_hash(db, "note.md") == "abc123"

    def test_update_overwrites_existing_hash(self, db) -> None:
        _update_hash(db, "note.md", "old")
        _update_hash(db, "note.md", "new")
        assert _get_stored_hash(db, "note.md") == "new"


class TestScanVault:
    """Test vault file scanning."""

    def test_finds_md_files(self, tmp_path) -> None:
        (tmp_path / "note1.md").write_text("hello")
        (tmp_path / "note2.md").write_text("world")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        results = _scan_vault(tmp_path)
        paths = [rel for _, rel in results]
        assert "note1.md" in paths
        assert "note2.md" in paths
        assert "image.png" not in paths

    def test_finds_nested_files(self, tmp_path) -> None:
        (tmp_path / "projects" / "repo").mkdir(parents=True)
        (tmp_path / "projects" / "repo" / "note.md").write_text("content")

        results = _scan_vault(tmp_path)
        paths = [rel for _, rel in results]
        assert "projects/repo/note.md" in paths

    def test_empty_vault_returns_empty(self, tmp_path) -> None:
        results = _scan_vault(tmp_path)
        assert results == []

    def test_results_are_sorted(self, tmp_path) -> None:
        (tmp_path / "b.md").write_text("b")
        (tmp_path / "a.md").write_text("a")

        results = _scan_vault(tmp_path)
        paths = [rel for _, rel in results]
        assert paths == sorted(paths)


class TestIndexReport:
    """Test IndexReport dataclass defaults."""

    def test_defaults_are_zero(self) -> None:
        report = IndexReport()
        assert report.total_notes == 0
        assert report.new_notes == 0
        assert report.changed_notes == 0
        assert report.unchanged_notes == 0
        assert report.deleted_notes == 0
        assert report.total_chunks == 0
        assert report.vectors_upserted == 0

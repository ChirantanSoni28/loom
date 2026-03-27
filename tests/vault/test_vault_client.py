"""Tests for loom.vault.VaultClient — facade with CLI/filesystem fallback."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from loom.config import LoomConfig
from loom.db import get_connection
from loom.vault import VaultClient
from loom.vault.sync import pending_count


@pytest.fixture()
def vault_path(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "projects").mkdir()
    return vault


@pytest.fixture()
def config(vault_path: Path) -> LoomConfig:
    return LoomConfig(vault_path=vault_path, obsidian_vault_name="test-vault")


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    return get_connection(tmp_path / "test.db")


class TestVaultClientOffline:
    """Test VaultClient behaviour when Obsidian is not running (offline mode)."""

    async def test_read_falls_back_to_filesystem(
        self, config: LoomConfig, db: sqlite3.Connection, vault_path: Path
    ) -> None:
        note_path = vault_path / "projects" / "test.md"
        note_path.write_text("# Test Note")

        with patch.object(
            VaultClient, "_is_online", new_callable=AsyncMock, return_value=False
        ):
            client = VaultClient(config, db=db)
            content = await client.read_note("projects/test.md")
            assert content == "# Test Note"

    async def test_write_queues_when_offline(
        self, config: LoomConfig, db: sqlite3.Connection, vault_path: Path
    ) -> None:
        with patch.object(
            VaultClient, "_is_online", new_callable=AsyncMock, return_value=False
        ):
            client = VaultClient(config, db=db)
            await client.write_note("projects/new.md", "# New Note")

        # Written to filesystem
        assert (vault_path / "projects" / "new.md").read_text() == "# New Note"
        # Also queued for sync
        assert pending_count(db) == 1

    async def test_search_falls_back_to_filesystem(
        self, config: LoomConfig, db: sqlite3.Connection, vault_path: Path
    ) -> None:
        note = vault_path / "projects" / "searchable.md"
        note.write_text("# Searchable\nFind this keyword here.")

        with patch.object(
            VaultClient, "_is_online", new_callable=AsyncMock, return_value=False
        ):
            client = VaultClient(config, db=db)
            results = await client.search("keyword")
            assert len(results) == 1
            assert "searchable.md" in results[0].path


class TestVaultClientOnline:
    """Test VaultClient behaviour when Obsidian CLI is available."""

    async def test_read_uses_cli(
        self, config: LoomConfig, db: sqlite3.Connection
    ) -> None:
        with patch.object(
            VaultClient, "_is_online", new_callable=AsyncMock, return_value=True
        ):
            client = VaultClient(config, db=db)
            client._cli.read_note = AsyncMock(return_value="# CLI Content")

            content = await client.read_note("projects/test.md")
            assert content == "# CLI Content"
            client._cli.read_note.assert_called_once_with("projects/test.md")

    async def test_write_uses_cli(
        self, config: LoomConfig, db: sqlite3.Connection
    ) -> None:
        with patch.object(
            VaultClient, "_is_online", new_callable=AsyncMock, return_value=True
        ):
            client = VaultClient(config, db=db)
            client._cli.write_note = AsyncMock()

            await client.write_note("projects/test.md", "# Content")
            client._cli.write_note.assert_called_once_with("projects/test.md", "# Content")
            # Nothing queued
            assert pending_count(db) == 0


class TestVaultClientFlush:
    async def test_flush_on_reconnect(
        self, config: LoomConfig, db: sqlite3.Connection, vault_path: Path
    ) -> None:
        from loom.vault.sync import queue_write

        await queue_write(db, "projects/queued.md", "# Queued")
        assert pending_count(db) == 1

        client = VaultClient(config, db=db)
        client._cli.write_note = AsyncMock()
        flushed = await client.flush_pending_writes()

        assert flushed == 1
        assert pending_count(db) == 0
        client._cli.write_note.assert_called_once_with("projects/queued.md", "# Queued")

"""VaultClient facade — Obsidian CLI first, filesystem fallback, offline write queue."""

import sqlite3
from pathlib import Path
from types import TracebackType

from obsidian_mcp import ObsidianCLI, SearchResult

from loom.config import LoomConfig
from loom.db import get_connection
from loom.vault.filesystem import FilesystemVaultClient, VaultOfflineError
from loom.vault.sync import flush_writes, queue_write


class VaultClient:
    """Unified vault access that tries Obsidian CLI first.

    If Obsidian is closed (health check fails), falls back to filesystem.
    Write operations when offline are queued in pending_writes (SQLite).
    Queued writes are flushed automatically next time Obsidian is reachable.
    """

    def __init__(self, config: LoomConfig, db: sqlite3.Connection | None = None) -> None:
        self._config = config
        self._cli = ObsidianCLI(vault_name=config.obsidian_vault_name)
        self._fs = FilesystemVaultClient(config.vault_path)
        self._db = db
        self._online: bool | None = None  # determined on first use

    async def __aenter__(self) -> "VaultClient":
        if self._db is None:
            self._db = get_connection()
        self._online = await self._cli.health_check()
        if self._online:
            # Flush any pending writes from previous offline sessions
            await self.flush_pending_writes()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def _is_online(self) -> bool:
        if self._online is None:
            self._online = await self._cli.health_check()
        return self._online

    def _ensure_db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = get_connection()
        return self._db

    async def read_note(self, path: str) -> str:
        """Read a note, preferring CLI, falling back to filesystem."""
        if await self._is_online():
            return await self._cli.read_note(path)
        return await self._fs.read_note(path)

    async def write_note(self, path: str, content: str) -> None:
        """Write a note via CLI, or queue for later if offline."""
        # Ensure vault directory structure exists for filesystem writes
        vault_path = self._config.vault_path
        target = vault_path / path
        target.parent.mkdir(parents=True, exist_ok=True)

        if await self._is_online():
            await self._cli.write_note(path, content)
        else:
            # Write to filesystem immediately for local access
            await self._fs.write_note(path, content)
            # Also queue for CLI sync when Obsidian reconnects
            await queue_write(self._ensure_db(), path, content)

    async def append_to_note(self, path: str, content: str) -> None:
        """Append to a note via CLI, or filesystem fallback."""
        if await self._is_online():
            await self._cli.append_to_note(path, content)
        else:
            await self._fs.append_to_note(path, content)

    async def list_directory(self, path: str) -> list[str]:
        """List files in a vault directory."""
        if await self._is_online():
            return await self._cli.list_files(folder=path)
        return await self._fs.list_directory(path)

    async def search(self, query: str) -> list[SearchResult]:
        """Search the vault, falling back to filesystem keyword search."""
        if await self._is_online():
            return await self._cli.search(query)
        return await self._fs.search(query)

    async def get_backlinks(self, path: str) -> list[str]:
        """Get backlinks to a note (requires Obsidian CLI)."""
        if not await self._is_online():
            raise VaultOfflineError("Backlinks require the Obsidian CLI")
        return await self._cli.get_backlinks(path)

    async def get_tags(self, path: str | None = None) -> list[str]:
        """Get tags, optionally for a specific file (requires Obsidian CLI)."""
        if not await self._is_online():
            raise VaultOfflineError("Tag queries require the Obsidian CLI")
        return await self._cli.get_tags(path=path)

    async def flush_pending_writes(self) -> int:
        """Flush all queued offline writes via the Obsidian CLI.

        Returns the number of writes flushed.
        """
        db = self._ensure_db()
        return await flush_writes(self._cli, db)

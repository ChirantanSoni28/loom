"""Direct filesystem access to the Loom vault — fallback when Obsidian is closed."""

import asyncio
from pathlib import Path

from obsidian_mcp import SearchResult


class VaultOfflineError(Exception):
    """Raised when an operation requires Obsidian but it is not available."""


class FilesystemVaultClient:
    """Read/write vault notes directly via the filesystem.

    Used as a fallback when the Obsidian CLI is unreachable.
    """

    def __init__(self, vault_path: Path) -> None:
        self._vault_path = vault_path

    def _resolve(self, path: str) -> Path:
        """Resolve a vault-relative path, ensuring it stays within the vault."""
        resolved = (self._vault_path / path).resolve()
        vault_resolved = self._vault_path.resolve()
        if not str(resolved).startswith(str(vault_resolved)):
            raise ValueError(f"Path traversal detected: {path}")
        return resolved

    async def read_note(self, path: str) -> str:
        """Read a note's content from the vault directory."""
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        return await asyncio.to_thread(target.read_text, encoding="utf-8")

    async def write_note(self, path: str, content: str) -> None:
        """Create or overwrite a note in the vault directory."""
        target = self._resolve(path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")

    async def append_to_note(self, path: str, content: str) -> None:
        """Append content to an existing note."""
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        existing = await asyncio.to_thread(target.read_text, encoding="utf-8")
        new_content = existing.rstrip("\n") + "\n\n" + content
        await asyncio.to_thread(target.write_text, new_content, encoding="utf-8")

    async def list_directory(self, path: str) -> list[str]:
        """List files in a vault directory."""
        target = self._resolve(path)
        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Directory not found: {path}")

        def _list() -> list[str]:
            vault_resolved = self._vault_path.resolve()
            return sorted(
                str(f.resolve().relative_to(vault_resolved))
                for f in target.iterdir()
                if f.is_file() and f.suffix == ".md"
            )

        return await asyncio.to_thread(_list)

    async def search(self, query: str) -> list[SearchResult]:
        """Simple keyword search across all .md files in the vault."""

        def _search() -> list[SearchResult]:
            results: list[SearchResult] = []
            query_lower = query.lower()
            vault_resolved = self._vault_path.resolve()
            for md_file in vault_resolved.rglob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                except OSError:
                    continue
                if query_lower in text.lower():
                    # Collect matching lines as context
                    matches = [
                        line.strip()
                        for line in text.splitlines()
                        if query_lower in line.lower()
                    ]
                    rel_path = str(md_file.relative_to(vault_resolved))
                    results.append(
                        SearchResult(path=rel_path, score=1.0, matches=matches[:5])
                    )
            return results

        return await asyncio.to_thread(_search)

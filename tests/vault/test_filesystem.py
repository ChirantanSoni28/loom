"""Tests for loom.vault.filesystem — direct file access fallback."""

from pathlib import Path

import pytest

from loom.vault.filesystem import FilesystemVaultClient
from obsidian_mcp import SearchResult


@pytest.fixture()
def vault(tmp_path: Path) -> FilesystemVaultClient:
    return FilesystemVaultClient(tmp_path)


@pytest.fixture()
def seeded_vault(tmp_path: Path) -> tuple[FilesystemVaultClient, Path]:
    """A vault with a couple of pre-existing notes."""
    note_dir = tmp_path / "projects" / "my-repo"
    note_dir.mkdir(parents=True)
    (note_dir / "session.md").write_text("# Session\nSome content about httpx.\n")
    (note_dir / "decision.md").write_text("# Decision\nChose sqlite for caching.\n")
    return FilesystemVaultClient(tmp_path), tmp_path


class TestReadNote:
    async def test_read_existing(self, seeded_vault: tuple[FilesystemVaultClient, Path]) -> None:
        client, _ = seeded_vault
        content = await client.read_note("projects/my-repo/session.md")
        assert "httpx" in content

    async def test_read_missing_raises(self, vault: FilesystemVaultClient) -> None:
        with pytest.raises(FileNotFoundError):
            await vault.read_note("nonexistent.md")


class TestWriteNote:
    async def test_write_creates_file(self, vault: FilesystemVaultClient, tmp_path: Path) -> None:
        await vault.write_note("projects/new/note.md", "# Hello\n")
        assert (tmp_path / "projects" / "new" / "note.md").read_text() == "# Hello\n"

    async def test_write_overwrites(self, vault: FilesystemVaultClient, tmp_path: Path) -> None:
        await vault.write_note("note.md", "v1")
        await vault.write_note("note.md", "v2")
        assert (tmp_path / "note.md").read_text() == "v2"


class TestAppendToNote:
    async def test_append(self, seeded_vault: tuple[FilesystemVaultClient, Path]) -> None:
        client, vault_path = seeded_vault
        await client.append_to_note("projects/my-repo/session.md", "## Appended")
        content = (vault_path / "projects" / "my-repo" / "session.md").read_text()
        assert content.endswith("## Appended")

    async def test_append_missing_raises(self, vault: FilesystemVaultClient) -> None:
        with pytest.raises(FileNotFoundError):
            await vault.append_to_note("missing.md", "content")


class TestListDirectory:
    async def test_list(self, seeded_vault: tuple[FilesystemVaultClient, Path]) -> None:
        client, _ = seeded_vault
        files = await client.list_directory("projects/my-repo")
        assert "projects/my-repo/session.md" in files
        assert "projects/my-repo/decision.md" in files

    async def test_list_missing_raises(self, vault: FilesystemVaultClient) -> None:
        with pytest.raises(FileNotFoundError):
            await vault.list_directory("nonexistent")


class TestSearch:
    async def test_keyword_match(self, seeded_vault: tuple[FilesystemVaultClient, Path]) -> None:
        client, _ = seeded_vault
        results = await client.search("httpx")
        assert len(results) == 1
        assert "session.md" in results[0].path

    async def test_case_insensitive(self, seeded_vault: tuple[FilesystemVaultClient, Path]) -> None:
        client, _ = seeded_vault
        results = await client.search("SQLITE")
        assert len(results) == 1
        assert "decision.md" in results[0].path

    async def test_no_match(self, seeded_vault: tuple[FilesystemVaultClient, Path]) -> None:
        client, _ = seeded_vault
        results = await client.search("nonexistent-term-xyz")
        assert results == []


class TestPathTraversal:
    async def test_traversal_blocked(self, vault: FilesystemVaultClient) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            await vault.read_note("../../etc/passwd")

"""Tests for obsidian_mcp.cli — Obsidian CLI subprocess wrapper."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from obsidian_mcp.cli import ObsidianCLI, ObsidianCLIError, SearchResult


def _mock_process(stdout: str = "", stderr: str = "", returncode: int = 0) -> AsyncMock:
    """Create a mock subprocess result."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(
        return_value=(stdout.encode(), stderr.encode())
    )
    proc.returncode = returncode
    return proc


class TestHealthCheck:
    async def test_healthy(self) -> None:
        cli = ObsidianCLI()
        with (
            patch("shutil.which", return_value="/usr/local/bin/obsidian"),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=_mock_process(stdout="1.8.0"),
            ),
        ):
            assert await cli.health_check() is True

    async def test_not_installed(self) -> None:
        cli = ObsidianCLI()
        with patch("shutil.which", return_value=None):
            assert await cli.health_check() is False

    async def test_not_responding(self) -> None:
        cli = ObsidianCLI()
        with (
            patch("shutil.which", return_value="/usr/local/bin/obsidian"),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=_mock_process(stderr="error", returncode=1),
            ),
        ):
            assert await cli.health_check() is False


class TestReadNote:
    async def test_success(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout="# Hello World\nSome content."),
        ):
            content = await cli.read_note("notes/hello.md")
            assert content == "# Hello World\nSome content."

    async def test_not_found(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stderr="File not found", returncode=1),
        ):
            with pytest.raises(FileNotFoundError):
                await cli.read_note("nonexistent.md")


class TestWriteNote:
    async def test_success(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(),
        ) as mock_exec:
            await cli.write_note("notes/new.md", "# New Note")
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert "create" in args
            assert "path=notes/new.md" in args
            assert "content=# New Note" in args
            assert "overwrite" in args


class TestAppend:
    async def test_success(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(),
        ) as mock_exec:
            await cli.append_to_note("notes/log.md", "New entry")
            args = mock_exec.call_args[0]
            assert "append" in args
            assert "path=notes/log.md" in args
            assert "content=New entry" in args


class TestSearch:
    async def test_json_results(self) -> None:
        cli = ObsidianCLI()
        json_output = json.dumps([
            {"path": "notes/a.md", "score": 1.0, "matches": ["line with keyword"]},
            {"path": "notes/b.md", "score": 0.8, "matches": ["another match"]},
        ])
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout=json_output),
        ):
            results = await cli.search("keyword")
            assert len(results) == 2
            assert results[0].path == "notes/a.md"
            assert results[0].matches == ["line with keyword"]

    async def test_empty_results(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout=""),
        ):
            results = await cli.search("nonexistent")
            assert results == []


class TestVaultName:
    async def test_vault_arg_included(self) -> None:
        cli = ObsidianCLI(vault_name="my-vault")
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout="1.8.0"),
        ) as mock_exec:
            await cli.version()
            args = mock_exec.call_args[0]
            assert "vault=my-vault" in args

    async def test_no_vault_arg_when_empty(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout="1.8.0"),
        ) as mock_exec:
            await cli.version()
            args = mock_exec.call_args[0]
            assert not any(a.startswith("vault=") for a in args)


class TestDeleteNote:
    async def test_success(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(),
        ) as mock_exec:
            await cli.delete_note("notes/old.md")
            args = mock_exec.call_args[0]
            assert "delete" in args
            assert "path=notes/old.md" in args


class TestListFiles:
    async def test_with_folder(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout="projects/a.md\nprojects/b.md"),
        ):
            files = await cli.list_files(folder="projects")
            assert files == ["projects/a.md", "projects/b.md"]

    async def test_empty(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(stdout=""),
        ):
            files = await cli.list_files()
            assert files == []


class TestBacklinks:
    async def test_json_results(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(
                stdout=json.dumps([{"path": "notes/referrer.md"}])
            ),
        ):
            backlinks = await cli.get_backlinks("notes/target.md")
            assert backlinks == ["notes/referrer.md"]


class TestTags:
    async def test_json_results(self) -> None:
        cli = ObsidianCLI()
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_mock_process(
                stdout=json.dumps([{"name": "python"}, {"name": "async"}])
            ),
        ):
            tags = await cli.get_tags()
            assert tags == ["python", "async"]

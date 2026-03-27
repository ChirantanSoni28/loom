"""Async subprocess wrapper for the Obsidian CLI."""

import asyncio
import json
import shutil
from dataclasses import dataclass


class ObsidianCLIError(Exception):
    """Raised when the Obsidian CLI returns a non-zero exit code."""

    def __init__(self, command: str, stderr: str) -> None:
        self.command = command
        super().__init__(f"obsidian {command} failed: {stderr}")


class ObsidianCLINotFoundError(Exception):
    """Raised when the Obsidian CLI binary is not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "Obsidian CLI not found. Ensure Obsidian is installed and the CLI is enabled:\n"
            "  Settings > General > Advanced > Command line interface"
        )


@dataclass
class SearchResult:
    """A single result from a vault search."""

    path: str
    score: float
    matches: list[str]


class ObsidianCLI:
    """Async wrapper around the Obsidian CLI binary.

    All commands are run as subprocesses. The optional vault_name parameter
    is passed as ``vault=<name>`` to target a specific vault.
    """

    def __init__(self, vault_name: str = "") -> None:
        self._vault_name = vault_name

    def _base_args(self) -> list[str]:
        """Build the base command with optional vault targeting."""
        args = ["obsidian"]
        if self._vault_name:
            args.append(f"vault={self._vault_name}")
        return args

    async def _run(self, *args: str, check: bool = True) -> str:
        """Run an obsidian CLI command and return stdout."""
        cmd = self._base_args() + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if check and proc.returncode != 0:
            command_str = " ".join(args)
            if "not found" in stderr.lower() or "no such file" in stderr.lower():
                raise FileNotFoundError(stderr)
            raise ObsidianCLIError(command_str, stderr)

        return stdout

    # ------------------------------------------------------------------
    # Health / info
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if the Obsidian CLI is available and responsive."""
        if shutil.which("obsidian") is None:
            return False
        try:
            await self._run("version")
            return True
        except (ObsidianCLIError, OSError):
            return False

    async def vault_info(self) -> str:
        """Get vault metadata (name, path, file count, etc.)."""
        return await self._run("vault")

    async def version(self) -> str:
        """Return the Obsidian version string."""
        return await self._run("version")

    # ------------------------------------------------------------------
    # Note CRUD
    # ------------------------------------------------------------------

    async def read_note(self, path: str) -> str:
        """Read a note's content by vault-relative path."""
        return await self._run("read", f"path={path}")

    async def write_note(self, path: str, content: str) -> None:
        """Create or overwrite a note at the given vault-relative path."""
        await self._run("create", f"path={path}", f"content={content}", "overwrite")

    async def append_to_note(self, path: str, content: str) -> None:
        """Append content to an existing note."""
        await self._run("append", f"path={path}", f"content={content}")

    async def prepend_to_note(self, path: str, content: str) -> None:
        """Prepend content to an existing note."""
        await self._run("prepend", f"path={path}", f"content={content}")

    async def delete_note(self, path: str) -> None:
        """Delete a note from the vault."""
        await self._run("delete", f"path={path}")

    async def move_note(self, path: str, to: str) -> None:
        """Move or rename a note."""
        await self._run("move", f"path={path}", f"to={to}")

    # ------------------------------------------------------------------
    # Properties (frontmatter)
    # ------------------------------------------------------------------

    async def read_property(self, path: str, name: str) -> str:
        """Read a frontmatter property value from a note."""
        return await self._run("property:read", f"path={path}", f"name={name}")

    async def set_property(self, path: str, name: str, value: str) -> None:
        """Set a frontmatter property on a note."""
        await self._run("property:set", f"path={path}", f"name={name}", f"value={value}")

    async def remove_property(self, path: str, name: str) -> None:
        """Remove a frontmatter property from a note."""
        await self._run("property:remove", f"path={path}", f"name={name}")

    async def list_properties(
        self, path: str | None = None, format: str = "json"
    ) -> str:
        """List properties in the vault or for a specific file."""
        args = ["properties", f"format={format}"]
        if path is not None:
            args.append(f"path={path}")
        return await self._run(*args)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        path: str | None = None,
        limit: int | None = None,
        case_sensitive: bool = False,
    ) -> list[SearchResult]:
        """Search the vault with context, returning structured results."""
        args = ["search:context", f"query={query}", "format=json"]
        if path is not None:
            args.append(f"path={path}")
        if limit is not None:
            args.append(f"limit={limit}")
        if case_sensitive:
            args.append("case")
        output = await self._run(*args)
        if not output:
            return []
        data = json.loads(output)
        results: list[SearchResult] = []
        if isinstance(data, list):
            for item in data:
                results.append(
                    SearchResult(
                        path=item.get("path", item.get("filename", "")),
                        score=item.get("score", 1.0),
                        matches=[
                            m if isinstance(m, str) else m.get("match", "")
                            for m in item.get("matches", item.get("lines", []))
                        ],
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    async def list_files(
        self, folder: str | None = None, ext: str | None = None
    ) -> list[str]:
        """List files in the vault, optionally filtered by folder or extension."""
        args = ["files"]
        if folder is not None:
            args.append(f"folder={folder}")
        if ext is not None:
            args.append(f"ext={ext}")
        output = await self._run(*args)
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def list_folders(self, folder: str | None = None) -> list[str]:
        """List folders in the vault."""
        args = ["folders"]
        if folder is not None:
            args.append(f"folder={folder}")
        output = await self._run(*args)
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Graph: links, backlinks, orphans, deadends
    # ------------------------------------------------------------------

    async def get_backlinks(self, path: str) -> list[str]:
        """List files that link to the given note."""
        output = await self._run("backlinks", f"path={path}", "format=json")
        if not output:
            return []
        data = json.loads(output)
        if isinstance(data, list):
            return [
                item.get("path", item) if isinstance(item, dict) else str(item)
                for item in data
            ]
        return []

    async def get_links(self, path: str) -> list[str]:
        """List outgoing links from a note."""
        output = await self._run("links", f"path={path}")
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def get_orphans(self) -> list[str]:
        """List files with no incoming links."""
        output = await self._run("orphans")
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def get_deadends(self) -> list[str]:
        """List files with no outgoing links."""
        output = await self._run("deadends")
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    async def get_tags(
        self, path: str | None = None, counts: bool = False
    ) -> list[str]:
        """List tags, optionally filtered to a specific file."""
        args = ["tags", "format=json"]
        if path is not None:
            args.append(f"path={path}")
        if counts:
            args.append("counts")
        output = await self._run(*args)
        if not output:
            return []
        data = json.loads(output)
        if isinstance(data, list):
            return [
                item.get("name", item) if isinstance(item, dict) else str(item)
                for item in data
            ]
        return []

    # ------------------------------------------------------------------
    # Daily notes
    # ------------------------------------------------------------------

    async def daily_read(self) -> str:
        """Read today's daily note content."""
        return await self._run("daily:read")

    async def daily_append(self, content: str) -> None:
        """Append content to today's daily note."""
        await self._run("daily:append", f"content={content}")

    async def daily_path(self) -> str:
        """Get the path of today's daily note."""
        return await self._run("daily:path")

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def list_tasks(
        self,
        path: str | None = None,
        done: bool = False,
        todo: bool = False,
        format: str = "json",
    ) -> str:
        """List tasks in the vault."""
        args = ["tasks", f"format={format}"]
        if path is not None:
            args.append(f"path={path}")
        if done:
            args.append("done")
        if todo:
            args.append("todo")
        return await self._run(*args)

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    async def sync_status(self) -> str:
        """Get the current Obsidian Sync status."""
        return await self._run("sync:status")

    async def sync_pause(self) -> None:
        """Pause Obsidian Sync."""
        await self._run("sync", "off")

    async def sync_resume(self) -> None:
        """Resume Obsidian Sync."""
        await self._run("sync", "on")

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    async def list_templates(self) -> list[str]:
        """List available templates."""
        output = await self._run("templates")
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def read_template(self, name: str, resolve: bool = False) -> str:
        """Read a template's content, optionally resolving variables."""
        args = ["template:read", f"name={name}"]
        if resolve:
            args.append("resolve")
        return await self._run(*args)

    # ------------------------------------------------------------------
    # Outline
    # ------------------------------------------------------------------

    async def get_outline(self, path: str, format: str = "json") -> str:
        """Get the heading outline of a note."""
        return await self._run("outline", f"path={path}", f"format={format}")

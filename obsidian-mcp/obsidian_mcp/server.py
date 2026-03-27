"""MCP server exposing Obsidian vault operations via the Obsidian CLI."""

import asyncio
import json
import os

from mcp.server import FastMCP

from obsidian_mcp.cli import ObsidianCLI, ObsidianCLIError, ObsidianCLINotFoundError

# Vault name can be configured via environment variable
_VAULT_NAME = os.environ.get("OBSIDIAN_VAULT", "")

server = FastMCP("obsidian")


def _get_cli() -> ObsidianCLI:
    return ObsidianCLI(vault_name=_VAULT_NAME)


# --------------------------------------------------------------------------
# Health / info
# --------------------------------------------------------------------------


@server.tool()
async def health_check() -> str:
    """Check if the Obsidian CLI is available and responsive."""
    cli = _get_cli()
    ok = await cli.health_check()
    return json.dumps({"healthy": ok})


@server.tool()
async def vault_info() -> str:
    """Get vault metadata (name, path, file count)."""
    cli = _get_cli()
    return await cli.vault_info()


@server.tool()
async def obsidian_version() -> str:
    """Get the Obsidian version."""
    cli = _get_cli()
    return await cli.version()


# --------------------------------------------------------------------------
# Note CRUD
# --------------------------------------------------------------------------


@server.tool()
async def read_note(path: str) -> str:
    """Read a note's markdown content by vault-relative path."""
    cli = _get_cli()
    return await cli.read_note(path)


@server.tool()
async def write_note(path: str, content: str) -> str:
    """Create or overwrite a note at the given vault-relative path."""
    cli = _get_cli()
    await cli.write_note(path, content)
    return json.dumps({"status": "written", "path": path})


@server.tool()
async def append_to_note(path: str, content: str) -> str:
    """Append content to an existing note."""
    cli = _get_cli()
    await cli.append_to_note(path, content)
    return json.dumps({"status": "appended", "path": path})


@server.tool()
async def prepend_to_note(path: str, content: str) -> str:
    """Prepend content to an existing note."""
    cli = _get_cli()
    await cli.prepend_to_note(path, content)
    return json.dumps({"status": "prepended", "path": path})


@server.tool()
async def delete_note(path: str) -> str:
    """Delete a note from the vault."""
    cli = _get_cli()
    await cli.delete_note(path)
    return json.dumps({"status": "deleted", "path": path})


@server.tool()
async def move_note(path: str, to: str) -> str:
    """Move or rename a note."""
    cli = _get_cli()
    await cli.move_note(path, to)
    return json.dumps({"status": "moved", "from": path, "to": to})


# --------------------------------------------------------------------------
# Properties (frontmatter)
# --------------------------------------------------------------------------


@server.tool()
async def read_property(path: str, name: str) -> str:
    """Read a frontmatter property value from a note."""
    cli = _get_cli()
    return await cli.read_property(path, name)


@server.tool()
async def set_property(path: str, name: str, value: str) -> str:
    """Set a frontmatter property on a note."""
    cli = _get_cli()
    await cli.set_property(path, name, value)
    return json.dumps({"status": "set", "path": path, "property": name, "value": value})


@server.tool()
async def remove_property(path: str, name: str) -> str:
    """Remove a frontmatter property from a note."""
    cli = _get_cli()
    await cli.remove_property(path, name)
    return json.dumps({"status": "removed", "path": path, "property": name})


@server.tool()
async def list_properties(path: str | None = None) -> str:
    """List properties in the vault or for a specific file. Returns JSON."""
    cli = _get_cli()
    return await cli.list_properties(path=path, format="json")


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


@server.tool()
async def search(
    query: str,
    path: str | None = None,
    limit: int | None = None,
    case_sensitive: bool = False,
) -> str:
    """Search the vault for text with matching line context. Returns JSON."""
    cli = _get_cli()
    results = await cli.search(
        query=query, path=path, limit=limit, case_sensitive=case_sensitive
    )
    return json.dumps(
        [{"path": r.path, "score": r.score, "matches": r.matches} for r in results]
    )


# --------------------------------------------------------------------------
# File / folder listing
# --------------------------------------------------------------------------


@server.tool()
async def list_files(folder: str | None = None, ext: str | None = None) -> str:
    """List files in the vault, optionally filtered by folder or extension. Returns JSON array."""
    cli = _get_cli()
    files = await cli.list_files(folder=folder, ext=ext)
    return json.dumps(files)


@server.tool()
async def list_folders(folder: str | None = None) -> str:
    """List folders in the vault. Returns JSON array."""
    cli = _get_cli()
    folders = await cli.list_folders(folder=folder)
    return json.dumps(folders)


# --------------------------------------------------------------------------
# Graph: links, backlinks, orphans, deadends
# --------------------------------------------------------------------------


@server.tool()
async def get_backlinks(path: str) -> str:
    """List files that link to the given note. Returns JSON array."""
    cli = _get_cli()
    backlinks = await cli.get_backlinks(path)
    return json.dumps(backlinks)


@server.tool()
async def get_links(path: str) -> str:
    """List outgoing links from a note. Returns JSON array."""
    cli = _get_cli()
    links = await cli.get_links(path)
    return json.dumps(links)


@server.tool()
async def get_orphans() -> str:
    """List files with no incoming links. Returns JSON array."""
    cli = _get_cli()
    orphans = await cli.get_orphans()
    return json.dumps(orphans)


@server.tool()
async def get_deadends() -> str:
    """List files with no outgoing links. Returns JSON array."""
    cli = _get_cli()
    deadends = await cli.get_deadends()
    return json.dumps(deadends)


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------


@server.tool()
async def get_tags(path: str | None = None, counts: bool = False) -> str:
    """List tags in the vault or for a file. Returns JSON array."""
    cli = _get_cli()
    tags = await cli.get_tags(path=path, counts=counts)
    return json.dumps(tags)


# --------------------------------------------------------------------------
# Daily notes
# --------------------------------------------------------------------------


@server.tool()
async def daily_read() -> str:
    """Read today's daily note content."""
    cli = _get_cli()
    return await cli.daily_read()


@server.tool()
async def daily_append(content: str) -> str:
    """Append content to today's daily note."""
    cli = _get_cli()
    await cli.daily_append(content)
    return json.dumps({"status": "appended"})


@server.tool()
async def daily_path() -> str:
    """Get the file path of today's daily note."""
    cli = _get_cli()
    return await cli.daily_path()


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


@server.tool()
async def list_tasks(
    path: str | None = None, done: bool = False, todo: bool = False
) -> str:
    """List tasks in the vault. Returns JSON."""
    cli = _get_cli()
    return await cli.list_tasks(path=path, done=done, todo=todo, format="json")


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


@server.tool()
async def sync_status() -> str:
    """Get the current Obsidian Sync status."""
    cli = _get_cli()
    return await cli.sync_status()


@server.tool()
async def sync_pause() -> str:
    """Pause Obsidian Sync."""
    cli = _get_cli()
    await cli.sync_pause()
    return json.dumps({"status": "paused"})


@server.tool()
async def sync_resume() -> str:
    """Resume Obsidian Sync."""
    cli = _get_cli()
    await cli.sync_resume()
    return json.dumps({"status": "resumed"})


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------


@server.tool()
async def list_templates() -> str:
    """List available templates. Returns JSON array."""
    cli = _get_cli()
    templates = await cli.list_templates()
    return json.dumps(templates)


@server.tool()
async def read_template(name: str, resolve: bool = False) -> str:
    """Read a template's content, optionally resolving variables."""
    cli = _get_cli()
    return await cli.read_template(name, resolve=resolve)


# --------------------------------------------------------------------------
# Outline
# --------------------------------------------------------------------------


@server.tool()
async def get_outline(path: str) -> str:
    """Get the heading outline of a note. Returns JSON."""
    cli = _get_cli()
    return await cli.get_outline(path, format="json")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    """Run the Obsidian MCP server via stdio."""
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()

# obsidian-mcp

MCP server for [Obsidian](https://obsidian.md) via the Obsidian CLI.

Exposes your Obsidian vault as MCP tools — read, write, search, tag, link, and sync notes from any MCP-compatible AI agent.

## Requirements

- Python 3.12+
- [Obsidian](https://obsidian.md) with CLI enabled (Settings > General > Advanced > Command line interface)

## Install

```bash
uv pip install obsidian-mcp
```

## Usage

### As an MCP server (stdio)

```bash
obsidian-mcp
# or
python -m obsidian_mcp
```

### Configure vault name

```bash
OBSIDIAN_VAULT=my-vault obsidian-mcp
```

### Claude Code integration

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "obsidian-mcp",
      "env": {
        "OBSIDIAN_VAULT": "my-vault"
      }
    }
  }
}
```

## Available Tools

### Note CRUD
- `read_note` — Read a note by path
- `write_note` — Create or overwrite a note
- `append_to_note` — Append content to a note
- `prepend_to_note` — Prepend content to a note
- `delete_note` — Delete a note
- `move_note` — Move or rename a note

### Properties (Frontmatter)
- `read_property` — Read a frontmatter property
- `set_property` — Set a frontmatter property
- `remove_property` — Remove a frontmatter property
- `list_properties` — List all properties

### Search
- `search` — Full-text search with line context (JSON)

### Navigation
- `list_files` — List files, optionally by folder/extension
- `list_folders` — List folders
- `get_outline` — Get heading outline of a note

### Graph
- `get_backlinks` — Files linking to a note
- `get_links` — Outgoing links from a note
- `get_orphans` — Files with no incoming links
- `get_deadends` — Files with no outgoing links

### Tags
- `get_tags` — List tags (vault-wide or per file)

### Daily Notes
- `daily_read` — Read today's daily note
- `daily_append` — Append to daily note
- `daily_path` — Get daily note path

### Tasks
- `list_tasks` — List tasks (filterable by done/todo)

### Sync
- `sync_status` — Obsidian Sync status
- `sync_pause` / `sync_resume` — Control sync

### Templates
- `list_templates` — List templates
- `read_template` — Read template content

### Info
- `health_check` — Check CLI availability
- `vault_info` — Vault metadata
- `obsidian_version` — Obsidian version

## As a Python library

```python
from obsidian_mcp import ObsidianCLI

async def main():
    cli = ObsidianCLI(vault_name="my-vault")
    content = await cli.read_note("projects/readme.md")
    results = await cli.search("keyword")
    backlinks = await cli.get_backlinks("notes/target.md")
```

## License

MIT

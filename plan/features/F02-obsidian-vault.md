# F02: Obsidian Vault Integration

**Status:** complete
**Depends on:** F01 (config + `~/.loom/vault/` layout exists)
**Review gate:** Can read/write notes to vault via Obsidian CLI; filesystem fallback works when Obsidian is closed; `obsidian-mcp` package works as a standalone MCP server

---

## Goal

Build the vault access layer using the official Obsidian CLI with a filesystem fallback. The CLI wrapper is packaged as a standalone MCP server (`obsidian-mcp/`) that can be used independently by any MCP-compatible agent. Loom imports `ObsidianCLI` directly as a Python library (no MCP serialization overhead) and adds a `VaultClient` facade with offline write queueing.

After this feature, Loom can read notes, write notes, search the vault, and parse wikilinks from markdown — regardless of whether Obsidian is open. External agents can access the same capabilities via the `obsidian-mcp` MCP server.

---

## Files

```
obsidian-mcp/                    ← standalone package (separate pyproject.toml)
  obsidian_mcp/
    cli.py                       ← async subprocess wrapper for Obsidian CLI
    server.py                    ← FastMCP server (30+ tools)
    __main__.py                  ← python -m obsidian_mcp entry point
    __init__.py                  ← public API exports
  tests/
    test_cli.py                  ← 16 tests
  pyproject.toml
  README.md

loom/
  vault/
    filesystem.py                ← direct .md file access (fallback)
    sync.py                      ← offline write queue (pending_writes table)
    markdown.py                  ← parse wikilinks, frontmatter, tags from .md
    __init__.py                  ← VaultClient facade (CLI first, fallback auto)
```

---

## Architecture: Direct Import vs MCP Protocol

Loom imports `ObsidianCLI` directly as a Python library:
```python
from obsidian_mcp import ObsidianCLI
```

This avoids MCP serialization overhead for in-process calls. The MCP server
(`obsidian-mcp`) exists as a separate entry point so external agents and tools
can access the same Obsidian CLI capabilities independently:

```bash
# External agents use the MCP server
obsidian-mcp                        # stdio transport
OBSIDIAN_VAULT=my-vault obsidian-mcp  # target specific vault
```

---

## Obsidian CLI Commands Used

| CLI Command | Purpose |
|-------------|---------|
| `obsidian read path=<path>` | Read a note's content |
| `obsidian create path=<path> content=<text> overwrite` | Create or overwrite a note |
| `obsidian append path=<path> content=<text>` | Append to a note |
| `obsidian prepend path=<path> content=<text>` | Prepend to a note |
| `obsidian files folder=<path>` | List files in a directory |
| `obsidian search:context query=<text> format=json` | Search with line context |
| `obsidian delete path=<path>` | Delete a note |
| `obsidian version` | Health check (is Obsidian CLI responsive?) |
| `obsidian backlinks path=<path> format=json` | List backlinks to a note |
| `obsidian tags format=json` | List tags in the vault |
| `obsidian property:read path=<path> name=<name>` | Read frontmatter property |
| `obsidian property:set path=<path> name=<name> value=<val>` | Set frontmatter property |
| `obsidian sync:status` | Check Obsidian Sync status |

All commands accept `vault=<name>` to target a specific vault.

---

## `ObsidianCLI` Interface (obsidian-mcp package)

```python
class ObsidianCLI:
    def __init__(self, vault_name: str = "") -> None
    async def health_check(self) -> bool
    async def read_note(self, path: str) -> str
    async def write_note(self, path: str, content: str) -> None
    async def append_to_note(self, path: str, content: str) -> None
    async def prepend_to_note(self, path: str, content: str) -> None
    async def delete_note(self, path: str) -> None
    async def move_note(self, path: str, to: str) -> None
    async def list_files(self, folder: str | None, ext: str | None) -> list[str]
    async def search(self, query: str, ...) -> list[SearchResult]
    async def get_backlinks(self, path: str) -> list[str]
    async def get_links(self, path: str) -> list[str]
    async def get_tags(self, path: str | None) -> list[str]
    async def read_property(self, path: str, name: str) -> str
    async def set_property(self, path: str, name: str, value: str) -> None
    async def sync_status(self) -> str
    async def vault_info(self) -> str
    # ... plus daily notes, tasks, templates, outline
```

---

## `filesystem.py` Interface (Fallback)

Direct reads/writes to `~/.loom/vault/` without Obsidian running.

```python
class FilesystemVaultClient:
    async def read_note(self, path: str) -> str
    async def write_note(self, path: str, content: str) -> None
    async def append_to_note(self, path: str, content: str) -> None
    async def list_directory(self, path: str) -> list[str]
    async def search(self, query: str) -> list[SearchResult]
    # NOTE: backlinks, tags, properties not available — raises VaultOfflineError
```

---

## `__init__.py` — VaultClient Facade

```python
class VaultClient:
    """
    Tries Obsidian CLI first.
    If Obsidian is closed (health check fails), falls back to filesystem.
    Write operations when offline are queued in pending_writes (SQLite).
    Queued writes flushed automatically next time Obsidian is reachable.
    """
    async def __aenter__(self) -> "VaultClient"
    async def __aexit__(self, ...) -> None

    async def read_note(self, path: str) -> str
    async def write_note(self, path: str, content: str) -> None
    async def append_to_note(self, path: str, content: str) -> None
    async def list_directory(self, path: str) -> list[str]
    async def search(self, query: str) -> list[SearchResult]
    async def get_backlinks(self, path: str) -> list[str]  # CLI-only
    async def get_tags(self, path: str | None) -> list[str]  # CLI-only
    async def flush_pending_writes(self) -> int
```

---

## `markdown.py` — Wikilink + Frontmatter Parser

```python
@dataclass
class ParsedNote:
    path: str
    frontmatter: dict          # YAML frontmatter key-value pairs
    wikilinks: list[str]       # [[linked note]] targets
    tags: list[str]            # #tags from frontmatter + inline
    body: str                  # content below frontmatter

def parse_note(path: str, content: str) -> ParsedNote
def extract_wikilinks(content: str) -> list[str]
def extract_frontmatter(content: str) -> dict
```

---

## Note Template Used by Loom

All notes written by Loom follow this frontmatter schema:

```markdown
---
date: 2026-03-26
project: my-repo
type: session          # session | decision | pattern | preference
tier: hot              # hot | warm | cold (sessions only)
tags: [loom, session]
related:
  - "[[projects/my-repo/decisions/use-sqlite]]"
  - "[[knowledge/tech/python]]"
---

## Summary
...

## Key Decisions
- [[decisions/use-sqlite]] — chose sqlite-vec for local graph cache

## Files Changed
- `loom/vault/filesystem.py`

## Patterns Observed
- Obsidian CLI subprocess pattern used for all vault calls
```

---

## Offline Write Queue (`sync.py`)

When Obsidian is closed:
1. `write_note` / `append_to_note` are written to `pending_writes` table in SQLite
2. On next `VaultClient` init: health check → if Obsidian is back → flush queue
3. Flush is ordered by `created_at` to preserve write sequence

```python
async def queue_write(db: Connection, vault_path: str, content: str) -> None
async def flush_writes(cli: ObsidianCLI, db: Connection) -> int
```

---

## Acceptance Criteria

- [x] `VaultClient.read_note()` reads a note via Obsidian CLI
- [x] `VaultClient.write_note()` creates a note in `~/.loom/vault/`
- [x] `VaultClient.append_to_note()` appends content to an existing note
- [x] `VaultClient.search()` returns keyword-matched notes
- [x] With Obsidian closed: writes queue to SQLite, reads fall back to filesystem
- [x] On reconnect: `flush_pending_writes()` replays queued writes in order
- [x] `parse_note()` correctly extracts frontmatter, wikilinks, and tags from a markdown file
- [x] Vault directory structure (`projects/`, `knowledge/`) created if missing on first write
- [x] `obsidian-mcp` package works as a standalone MCP server (30+ tools)
- [x] `obsidian-mcp` has its own test suite (16 tests passing)
- [x] Loom imports `ObsidianCLI` directly (no MCP overhead for in-process calls)

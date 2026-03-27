# F03: MCP Server Core

**Status:** pending
**Depends on:** F01 (config), F02 (VaultClient)
**Review gate:** MCP server starts, Claude Code discovers it, `loom_context` tool returns project notes

---

## Goal

Stand up the Python MCP server with stdio transport. Expose the five core tools as stubs that return real data where the underlying systems are ready (vault read/write), and placeholder responses where they depend on later features (vector search, graph traversal). After this feature, Claude Code can talk to Loom via MCP.

---

## Files

```
loom/
  server.py          ← MCP server definition (tools + resources)
  __main__.py        ← starts server when `python -m loom` or `loom serve`
```

`.claude-plugin/` (updated from F01):
```
.claude-plugin/
  .mcp.json          ← registers loom MCP server with Claude Code
```

---

## MCP Tools

### `loom_context`
Load project context at session start. Returns architecture.md + recent sessions.

**Input:**
```json
{ "repo_path": "/Users/user/workspace/my-repo" }
```

**Output:**
```markdown
## Project: my-repo

### Architecture
[contents of projects/my-repo/architecture.md]

### Recent Sessions (last 3)
[excerpts from sessions/hot/]

### Key Decisions
[list from decisions/]
```

**Available in F03:** reads vault directly via VaultClient.

---

### `loom_capture`
Write a note or decision to the vault.

**Input:**
```json
{
  "type": "session",
  "project": "my-repo",
  "title": "2026-03-26 session",
  "content": "## Summary\n...",
  "related": ["[[decisions/use-sqlite]]"]
}
```

**Output:** `{ "path": "projects/my-repo/sessions/hot/2026-03-26.md", "status": "written" }`

**Available in F03:** writes via VaultClient.

---

### `loom_search`
Hybrid search across vault. Returns ranked results with excerpts.

**Input:**
```json
{ "query": "auth decisions", "project": "my-repo", "limit": 5 }
```

**Output:**
```json
[
  { "path": "projects/my-repo/decisions/auth-jwt.md", "score": 0.92, "excerpt": "..." },
  { "path": "knowledge/patterns/jwt-refresh.md", "score": 0.87, "excerpt": "..." }
]
```

**F03 stub:** returns keyword search results only (Obsidian `/search/simple/`). Full hybrid search added in F07.

---

### `loom_relate`
Find notes connected to a given note via wikilinks.

**Input:**
```json
{ "path": "projects/my-repo/decisions/auth-jwt.md", "depth": 2 }
```

**Output:**
```json
[
  { "path": "knowledge/tech/jwt.md", "hops": 1 },
  { "path": "projects/my-repo/architecture.md", "hops": 1 }
]
```

**F03 stub:** returns empty list. Populated in F06 (graph traversal).

---

### `loom_compress`
Manually trigger compression for a project.

**Input:**
```json
{ "project": "my-repo", "dry_run": true }
```

**Output:** `{ "sessions_to_compress": 5, "status": "dry_run" }`

**F03 stub:** returns dry-run report only. Full compression added in F08.

---

## MCP Resources

```python
@server.resource("loom://project/{repo}")
async def project_overview(repo: str) -> str:
    """Returns architecture.md for the given repo."""

@server.resource("loom://knowledge/preferences")
async def user_preferences() -> str:
    """Returns knowledge/preferences/ notes."""
```

---

## `.claude-plugin/.mcp.json`

```json
{
  "mcpServers": {
    "loom": {
      "command": "python",
      "args": ["-m", "loom"],
      "env": {}
    }
  }
}
```

---

## `server.py` Structure

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("loom")

@server.tool()
async def loom_context(repo_path: str) -> str: ...

@server.tool()
async def loom_capture(type: str, project: str, title: str, content: str, related: list[str]) -> dict: ...

@server.tool()
async def loom_search(query: str, project: str | None, limit: int = 5) -> list[dict]: ...

@server.tool()
async def loom_relate(path: str, depth: int = 2) -> list[dict]: ...

@server.tool()
async def loom_compress(project: str, dry_run: bool = True) -> dict: ...

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## Acceptance Criteria

- [ ] `python -m loom` starts the MCP server without errors
- [ ] `claude mcp list` shows `loom` server registered
- [ ] `loom_context` returns architecture.md + recent sessions for a given repo path
- [ ] `loom_capture` writes a note to `~/.loom/vault/` and returns the file path
- [ ] `loom_search` returns keyword search results (stub — full hybrid in F07)
- [ ] `loom_relate` returns empty list without crashing (stub — graph in F06)
- [ ] `loom_compress` returns dry-run report without crashing (stub — logic in F08)
- [ ] MCP resources `loom://project/{repo}` and `loom://knowledge/preferences` return content

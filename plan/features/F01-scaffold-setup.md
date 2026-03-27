# F01: Project Scaffold + Setup Wizard

**Status:** complete
**Depends on:** nothing
**Review gate:** `loom setup` completes, `~/.loom/` structure exists, `loom --help` works

---

## Goal

Create the project foundation: Python package structure, CLI entry point, and interactive setup wizard. After this feature, the package is installable, `~/.loom/` is initialized with the correct layout, and all config is written to `loom-settings.json`. No vault access or MCP yet — just the foundation everything else builds on.

---

## Repository Structure

```
loom/
  loom/
    __main__.py          ← `python -m loom` entry point
    cli.py               ← Typer CLI (setup, config, reindex, --help)
    config.py            ← load/write ~/.loom/loom-settings.json
    db.py                ← SQLite schema init + connection helper
    __init__.py
  .claude-plugin/
    plugin.json          ← plugin manifest
    .mcp.json            ← placeholder, populated in F03
    settings.json        ← placeholder hooks, populated in F04
  scripts/
    install.sh           ← post-plugin-install hook (runs `loom setup`)
  pyproject.toml
  README.md
```

---

## `pyproject.toml` Dependencies

```toml
[project]
name = "loom-claude"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "mcp>=1.0",
    "pinecone>=5.0",
    "anthropic>=0.40",
    "rich>=13.0",
]

[project.scripts]
loom = "loom.cli:app"
```

---

## `loom setup` Wizard Flow

```
$ loom setup

[1/7] Checking Ollama...
      ✓ Ollama found (v0.3.x)
      → Pulling nomic-embed-text...  ✓

[2/7] Creating ~/.loom/ directory structure...
      ✓ ~/.loom/vault/projects/
      ✓ ~/.loom/vault/knowledge/
      ✓ ~/.loom/index.db  (schema initialized)

[3/7] Obsidian REST API
      Install the 'Local REST API' community plugin in Obsidian,
      then paste your API key below.
      API key: ████████████████

[4/7] Pinecone
      API key: ████████████████
      → Creating index 'loom-vault' (768 dims, cosine)...  ✓

[5/7] Anthropic API key (optional — for compression feature)
      Press Enter to skip (compression will remain disabled)
      API key: [skipped]

[6/7] Writing ~/.loom/loom-settings.json...  ✓

[7/7] Done!
      Run `loom config show` to review settings.
      Next: open Obsidian pointed at ~/.loom/vault/
```

**Hard failure conditions:**
- Ollama not installed → print install URL, exit code 1
- Pinecone key invalid → show error, re-prompt

---

## `config.py` Interface

```python
@dataclass
class LoomConfig:
    vault_path: Path
    obsidian_api_key: str
    obsidian_port: int
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    ollama_base_url: str
    pinecone_api_key: str
    pinecone_index_name: str
    compression_enabled: bool
    compression_require_approval: bool
    compression_anthropic_key: str | None
    hot_ttl_days: int
    warm_ttl_days: int

def load_config() -> LoomConfig:
    """Load from ~/.loom/loom-settings.json. Raises with helpful message if not found."""

def save_config(config: LoomConfig) -> None:
    """Write to ~/.loom/loom-settings.json."""
```

---

## SQLite Schema (`db.py`)

```sql
CREATE TABLE IF NOT EXISTS sync_state (
    path        TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    indexed_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_writes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_path  TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_cache (
    from_path   TEXT NOT NULL,
    to_path     TEXT NOT NULL,
    PRIMARY KEY (from_path, to_path)
);
```

---

## CLI Commands After F01

| Command | Description |
|---------|-------------|
| `loom setup` | Interactive first-time setup wizard |
| `loom config show` | Print current settings (API keys masked) |
| `loom config set <key> <value>` | Update a single setting |
| `loom --help` | List all commands |

---

## Acceptance Criteria

- [ ] `pip install loom-claude` (or `uv add loom-claude`) works
- [ ] `loom setup` runs interactively and produces a valid `~/.loom/loom-settings.json`
- [ ] `loom setup` exits with code 1 and helpful message if Ollama is not installed
- [ ] `~/.loom/vault/`, `~/.loom/index.db` created with correct structure
- [ ] `loom config show` prints settings with masked API keys
- [ ] `loom --help` lists all commands
- [ ] `config.py` raises `LoomConfigNotFoundError` with setup instructions if config missing

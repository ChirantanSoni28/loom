# Changelog

All notable changes to Loom are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Zero-Friction Setup Overhaul

#### Added
- `loom/retrieval/chroma_store.py` — ChromaDB PersistentClient as local vector store (replaces Pinecone)
- `loom/services/ollama_manager.py` — OllamaManager for automatic install, start, and model pull
- `loom/services/__init__.py` — services package
- `--non-interactive` flag on `loom setup` for fully unattended installation
- Ollama auto-recovery in `embedder.py` — on connection failure, attempts to restart Ollama before raising error
- `chroma_path` config field (default `~/.loom/chroma`)

#### Changed
- `loom setup` is now a 5-step fully automatic wizard (was 7-step interactive requiring Pinecone API key)
- Vector store switched from Pinecone (cloud, requires API key) to ChromaDB (local, zero-config)
- `indexer.py`, `hybrid.py`, `__init__.py` now use ChromaStore instead of PineconeStore
- `scripts/install.sh` runs `loom setup --non-interactive` for fully automatic post-install
- `scripts/e2e_test.sh` updated to import ChromaStore and OllamaManager

#### Removed
- `pinecone` dependency from `pyproject.toml`
- `loom/retrieval/pinecone_store.py` — PineconeStore class
- `pinecone_api_key` and `pinecone_index_name` config fields
- Pinecone API key prompt from setup wizard

---

### F01 — Project Scaffold + Setup Wizard

#### Added
- Python package structure (`loom/` with `__init__`, `__main__`, `cli`, `config`, `db` modules)
- `pyproject.toml` with hatchling build backend, all core dependencies, and dev tooling (pytest, mypy, ruff)
- `LoomConfig` dataclass with `load_config()`, `save_config()`, `set_config_value()` — reads/writes `~/.loom/loom-settings.json`
- `LoomConfigNotFoundError` with actionable setup instructions
- API key masking in `loom config show` (last 4 chars visible)
- Secure file permissions (600) on `loom-settings.json`
- SQLite schema for `sync_state`, `pending_writes`, `graph_cache` tables in `~/.loom/index.db`
- `loom setup` — 7-step interactive wizard (Ollama check, vault dirs, Obsidian/Pinecone/Anthropic keys, config write)
- `loom config show` — print settings with masked secrets
- `loom config set <key> <value>` — update a single setting with type coercion
- `loom --help` — command listing
- `python -m loom` — entry point stub (MCP server deferred to F03)
- `.claude-plugin/` scaffolding: `plugin.json`, `.mcp.json` placeholder, `settings.json` placeholder
- `scripts/install.sh` — post-plugin-install hook
- `README.md` — minimal project readme
- Unit tests for `config.py` and `db.py` (20 tests)

### F02 — Obsidian Vault Integration

#### Added
- **`obsidian-mcp/`** — standalone MCP server package for Obsidian via the Obsidian CLI
  - `obsidian_mcp/cli.py` — async subprocess wrapper for the full Obsidian CLI (note CRUD, search, backlinks, tags, properties, daily notes, tasks, sync, templates, outline)
  - `obsidian_mcp/server.py` — FastMCP server exposing all CLI methods as MCP tools (30+ tools)
  - `obsidian_mcp/__main__.py` — `python -m obsidian_mcp` entry point
  - Own `pyproject.toml`, README, and test suite (16 tests)
  - Usable independently by any MCP-compatible agent — no Loom dependency required
- `loom/vault/filesystem.py` — direct `.md` file access fallback with path traversal protection
- `loom/vault/sync.py` — offline write queue (pending_writes SQLite table) with ordered flush on reconnect
- `loom/vault/markdown.py` — wikilink, YAML frontmatter, and tag parser (`ParsedNote` dataclass)
- `loom/vault/__init__.py` — `VaultClient` facade: Obsidian CLI first, filesystem fallback, auto-flush on reconnect
- `VaultOfflineError` exception for operations requiring the Obsidian CLI
- Test fixtures vault (`tests/fixtures/vault/`) with sample session and knowledge notes
- Unit tests for filesystem, markdown, sync, and VaultClient modules (35 tests)

#### Changed
- Replaced Obsidian Local REST API with official Obsidian CLI for vault access
- Config: replaced `obsidian_api_key` / `obsidian_port` with `obsidian_vault_name`
- Setup wizard step 3 now asks for vault name instead of REST API key
- Loom depends on `obsidian-mcp` as a local path dependency

#### Architecture Decision: Direct import vs MCP protocol
Loom imports `ObsidianCLI` directly as a Python library (`from obsidian_mcp import ObsidianCLI`)
rather than consuming it via the MCP protocol. This avoids MCP serialization overhead for
in-process calls. The MCP server (`obsidian-mcp`) exists as a separate entry point so external
agents and tools can access the same Obsidian CLI capabilities independently.

# Loom — Claude Code Operating Manual

> This file is read automatically by Claude Code at every session start.
> It defines how to work with this codebase: conventions, constraints, security rules, and project context.

---

## Project Overview

**Loom** is an open-source Claude Code plugin that provides persistent, cross-session memory backed by an Obsidian vault. It captures Claude Code sessions automatically via hooks, stores structured knowledge in a local Obsidian vault, and retrieves relevant context using a hybrid vector + graph search pipeline.

**Repository:** `github.com/chirantansoni/loom`
**License:** MIT
**Status:** Active development — feature-gated, reviewed after each feature

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.12+ |
| MCP SDK | `mcp` (Anthropic official) | >=1.0 |
| CLI | `typer` + `rich` | >=0.12 |
| HTTP client | `httpx` (async) | >=0.27 |
| Vector store | ChromaDB (local) | >=0.5 |
| Embeddings | Ollama (local) | hard dependency |
| Default model | `nomic-embed-text` | 768-dim |
| LLM compression | Ollama (default) or `anthropic` SDK (optional) | — / >=0.40 |
| Default compression model | `llama3.2` (Ollama) | configurable |
| Graph cache | SQLite (stdlib) | — |
| Link review UI | `fastapi` + `uvicorn` | >=0.111 / >=0.29 |
| Vault access | Obsidian CLI (`obsidian-mcp` package) | subprocess |
| Config | JSON (`~/.loom/loom-settings.json`) | — |
| Package manager | `uv` (preferred) or `pip` | — |

---

## Architecture Principles

1. **Local-first**: All data lives in `~/.loom/` — vault, ChromaDB vectors, SQLite cache. No cloud services required.
2. **Obsidian as source of truth**: The vault is human-readable, human-editable markdown. Never store critical data only in SQLite or ChromaDB.
3. **Graceful degradation**: If Obsidian is closed, writes queue to SQLite and flush on reconnect. If Ollama is stopped, the embedder auto-restarts it.
4. **Ollama is a hard dependency**: Do not add fallback paths that skip embedding. Fail clearly with install instructions.
5. **User consent for compression**: Compression is `disabled` by default. Never compress without explicit user opt-in.
6. **MCP stdio transport**: The MCP server communicates via stdio, not HTTP. No external ports opened by the server process.
7. **Zero-config setup**: `loom setup` must work with no user input and no external accounts. Ollama is auto-installed and auto-started.

---

## Development Setup

```bash
# Install dependencies
uv sync

# Run the MCP server manually
python -m loom

# Run the CLI
loom --help

# Run tests
uv run pytest

# Type check
uv run mypy loom/

# Lint
uv run ruff check loom/
```

---

## Repository Structure

```
loom/
  loom/                    <- Python package
    __main__.py            <- entry point (`python -m loom`)
    cli.py                 <- Typer CLI (setup, reindex, graph, find-links, review-links, compress)
    config.py              <- loom-settings.json loader (incl. semantic_links_* fields)
    db.py                  <- SQLite schema + connection (7 tables)
    server.py              <- MCP server (tools + resources)
    capture/               <- event buffer, classifier, note builder
    retrieval/             <- embedder, chunker, chroma, graph, hybrid, semantic_links
      embedder.py          <- Ollama HTTP client with auto-start recovery
      chunker.py           <- Async semantic + heading-aware chunker, content-addressed IDs
      chroma_store.py      <- ChromaDB vector store (upsert/query/delete/get-by-id)
      indexer.py           <- Chunk-level incremental indexer + note-level mean-pool embeddings
      graph.py             <- Wikilink BFS traversal (SQLite-backed)
      hybrid.py            <- 3-stage retrieval + on-search link queuing
      semantic_links.py    <- Pairwise similarity discovery -> pending_links queue
    ui/                    <- Local link review web UI
      server.py            <- FastAPI app (approve/reject semantic links, trigger discovery)
    compression/           <- scheduler, summarizer, extractor
    services/              <- Ollama lifecycle manager
    vault/                 <- VaultClient facade, filesystem fallback, sync, markdown parser
  obsidian-mcp/            <- standalone MCP server for Obsidian (separate package)
    obsidian_mcp/
      cli.py               <- async subprocess wrapper for Obsidian CLI
      server.py            <- FastMCP server (30+ tools)
      __main__.py          <- `python -m obsidian_mcp` entry point
    tests/
    pyproject.toml
    README.md
  .claude-plugin/          <- Claude Code plugin manifest + hooks config
  plan/                    <- architecture docs and feature breakdown
    VISION.md
    features/F0N-*.md
  scripts/                 <- install + test scripts
  tests/                   <- pytest test suite
  pyproject.toml
  CLAUDE.md                <- this file
  README.md
```

---

## Code Conventions

### Python style
- **Type hints on all public functions** — no untyped function signatures
- **Async-first**: all I/O-bound operations use `async`/`await`. No `time.sleep` in async code.
- **Dataclasses over dicts** for structured data crossing module boundaries
- **Explicit error types**: define domain-specific exceptions (e.g., `OllamaNotAvailableError`, `VaultOfflineError`, `LoomConfigNotFoundError`)
- **No bare `except`** — always catch specific exception types

### File organisation
- One class/concern per module where possible
- Public interface in `__init__.py` of each sub-package
- Tests mirror source structure: `tests/capture/test_classifier.py` for `loom/capture/classifier.py`

### Imports
- Absolute imports only (`from loom.config import load_config`, not relative)
- Group: stdlib -> third-party -> internal

### Naming
- `snake_case` for functions, variables, files
- `PascalCase` for classes
- `UPPER_CASE` for module-level constants
- Prefix private helpers with `_`

---

## Security Standards

### Secret handling
- **Never hardcode API keys** in source code or tests
- All secrets live in `~/.loom/loom-settings.json` (user home dir, not project dir)
- `loom config show` must **mask** API keys (show only last 4 chars: `...abcd`)
- `loom-settings.json` must have file permissions `600` (owner read/write only) — enforced by setup wizard
- Never log full API keys — log key name and masked value only

### Vault access
- Vault operations use the Obsidian CLI (subprocess) or direct filesystem access (fallback)
- Only read/write within `~/.loom/vault/` — never traverse outside the configured vault path
- Path traversal protection: validate all vault paths are under `config.vault_path` before any file operation

### Input validation
- Sanitize all user-supplied strings before using as file paths (`pathlib.Path` + `resolve()`)
- Wikilink targets from vault must not be used as shell arguments
- MCP tool inputs are validated against typed schemas before processing

### Dependencies
- Pin all dependency versions in `pyproject.toml` with minimum bounds
- Run `uv audit` before each release to check for known vulnerabilities
- Do not add dependencies with GPL/LGPL licenses (MIT/Apache only)

### Data handling
- No telemetry, analytics, or usage reporting — ever
- ChromaDB vectors and vault content are local-only; treat as sensitive (same handling as source code)
- Do not send vault content to external services beyond: Anthropic API (compression, opt-in only, only when `compression_llm_provider = "anthropic"`). Default compression uses Ollama (local).

---

## Compliance & Privacy

| Concern | Policy |
|---------|--------|
| Data residency | All data is local by default: vault, ChromaDB, SQLite. No cloud services required. |
| External API calls | Ollama: localhost only. Anthropic API: opt-in, user's own key, only when `compression_llm_provider = "anthropic"`. |
| Vault sync | Obsidian Sync is user-configured and user-managed. Loom has no opinion on sync provider. |
| PII in notes | Loom does not redact PII. Users are responsible for what they capture in the vault. |
| Open source | MIT license. No contributor CLA required. |

---

## Feature Development Workflow

1. Pick the next feature from `plan/features/`
2. Read the feature file fully before writing any code
3. Implement all files listed under "Files" section
4. Verify all acceptance criteria listed at the bottom of the feature file
5. **Do not proceed to the next feature until the current one is reviewed by the user**
6. Update `plan/VISION.md` feature table status: `pending` -> `in_progress` -> `complete`
7. **Update `CHANGELOG.md`** — log all added/changed/removed items under the feature heading before moving on

---

## Key Constraints (Do Not Violate)

- **Ollama required**: Never add a code path that skips embedding or falls back to non-Ollama embedding without user config change
- **Compression is opt-in**: `compression.enabled` defaults to `false`. Never enable it automatically. Compression uses Ollama by default (`compression_llm_provider = "ollama"`); an Anthropic key is only required when the user explicitly sets `compression_llm_provider = "anthropic"`.
- **Semantic links require approval**: `pending_links` entries must never be written to the vault as wikilinks without explicit user approval via `loom review-links`. The `auto_on_search` config gate defaults to `false`.
- **Vault path is `~/.loom/vault/`**: Do not use the user's existing Obsidian vault. Loom manages its own vault.
- **MCP tools never block**: Hooks (`buffer-event`, `flush`) must exit quickly. Heavy work is async and non-blocking.
- **No feature flags in production code**: Features are either complete or stubbed with a clear `NotImplementedError`. No `if DEBUG` branches in shipped code.
- **SQLite is local only**: Never replicate SQLite data to a remote service. It is a local cache, not source of truth.
- **ChromaDB is local only**: Vector data stays on disk at `~/.loom/chroma/`. Never send vectors to external services.
- **`chunk_note()` is async**: It accepts an optional `OllamaEmbedder` for semantic breakpoint detection. Always `await` it; never call it synchronously.

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `loom setup` | Fully automatic setup (installs Ollama, creates vault, inits ChromaDB) |
| `loom setup --non-interactive` | Unattended setup with all defaults |
| `loom config show` | Print settings (keys masked) |
| `loom config set <key> <val>` | Update a single setting |
| `loom reindex` | Incrementally sync vault to ChromaDB (chunk-level skip for unchanged chunks) |
| `loom reindex --force` | Full re-embed all vault notes |
| `loom graph rebuild` | Rebuild wikilink graph cache in SQLite |
| `loom graph stats` | Print node/edge counts |
| `loom find-links` | Scan note embeddings, queue semantically similar pairs for review |
| `loom review-links` | Start browser UI at localhost:7842 to approve/reject link suggestions |
| `loom review-links --port N` | Use a custom port |
| `loom compress --project <name>` | Run compression for a project |
| `loom compress --dry-run` | Show what would be compressed |
| `loom buffer-event` | (Hook) Buffer a tool event to SQLite |
| `loom flush` | (Hook) Flush event buffer to vault note |
| `loom context-hook` | (Hook) Load project context at session start |
| `python -m loom` | Start MCP server (stdio) |

---

## MCP Tools Reference

| Tool | When called | Purpose |
|------|-------------|---------|
| `loom_context` | SessionStart | Load project architecture + recent sessions |
| `loom_search` | On-demand | Hybrid vector + graph search across vault |
| `loom_capture` | Stop hook | Write session note or decision to vault |
| `loom_relate` | On-demand | Find graph neighbors of a vault note |
| `loom_compress` | On-demand / approval | Run compression cycle for a project |

---

## Testing Standards

- **Unit tests** for: classifier, note_builder, chunker, graph BFS, config loader
- **Integration tests** for: VaultClient (against live Obsidian or filesystem fallback), ChromaDB upsert/query, hybrid retrieval pipeline
- **No mocking of Ollama** — tests requiring embeddings use a `test` fixture model or skip if Ollama not available
- Test vault: `tests/fixtures/vault/` — a small seed vault with known notes and wikilinks
- All tests must pass before merging to `main`
- CI: GitHub Actions, runs on Python 3.12, macOS + Ubuntu

---

## Decisions Log

| Decision | Rationale |
|----------|-----------|
| Python over TypeScript | Richer async AI ecosystem; anthropic SDK is Python-native |
| ChromaDB over Pinecone | Local-first, zero-config, no external accounts needed; privacy-first |
| Ollama as hard dependency | Avoids API costs for embeddings; local privacy; clear failure message is better than silent fallback |
| Separate `~/.loom/vault/` | Avoids polluting user's existing Obsidian vault with auto-generated content |
| Obsidian CLI over REST API | Official CLI supports headless sync (remote vaults), backlinks, tags, properties natively; REST API was a community plugin. CLI packaged as standalone `obsidian-mcp` MCP server for reuse. |
| Direct import over MCP protocol | Loom imports `ObsidianCLI` as a Python library to avoid MCP serialization overhead; the MCP server exists as a separate entry point for external agents |
| Compression opt-in | User data safety; compression is irreversible without archive; trust must be earned |
| `loom-settings.json` (not TOML/env) | JSON is stdlib-parseable, familiar, and easy to generate from setup wizard |
| Semantic chunking (Ollama-guided, async) | Splits at meaning changes rather than character counts; heading breadcrumbs preserve retrieval context |
| Content-addressed chunk IDs | `{path}#{sha256(text)[:8]}` — stable IDs enable chunk-level incremental skip, avoiding re-embedding unchanged text |
| Mean-pooled note embedding in SQLite | Single compact vector per note (packed float BLOB) allows stdlib-only pairwise cosine similarity; no numpy required |
| User-approval gate for semantic links | Prevents vault pollution from false-positive similarity matches; `loom review-links` UI is the only write path |
| Ollama-first compression LLM | Compression summarization defaults to Ollama (already a hard dependency) — no extra API key or account required. Anthropic remains available as an opt-in alternative via `compression_llm_provider = "anthropic"`. |

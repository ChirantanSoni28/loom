# Loom

Obsidian-backed graph retrieval memory for Claude Code. Loom automatically captures your coding sessions, stores structured knowledge in a local Obsidian vault, and retrieves relevant context using a hybrid vector + graph search pipeline — giving Claude Code persistent, cross-session memory.

## Prerequisites

| Dependency | Why | Install |
|---|---|---|
| **Python 3.12+** | Runtime | [python.org](https://www.python.org/downloads/) |
| **Ollama** | Local embeddings | Auto-installed by `loom setup` if missing |
| **Obsidian** (optional) | Rich vault browsing, backlinks, tags | [obsidian.md](https://obsidian.md/) |
| **Anthropic API key** (optional) | Compression via Anthropic (not required — Ollama is used by default) | [console.anthropic.com](https://console.anthropic.com/) |

No external accounts or API keys are required for core functionality. Loom uses ChromaDB (local) for vector storage and Ollama (local) for embeddings.

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/chirantansoni/loom.git
cd loom

# 2. Install (uv preferred, pip also works)
uv pip install -e .

# 3. Run the setup wizard (fully automatic)
loom setup
```

The setup wizard runs 5 automatic steps — no prompts required:

1. **Ollama** — installs if missing, starts server, pulls `nomic-embed-text` model
2. **Vault** — creates `~/.loom/vault/` directory tree (projects/, knowledge/)
3. **Database** — creates SQLite schema at `~/.loom/index.db`
4. **Vector store** — initializes ChromaDB at `~/.loom/chroma/`
5. **Config** — writes `~/.loom/loom-settings.json` (mode 600)

For fully unattended setup (CI, scripts): `loom setup --non-interactive`

After setup, optionally point Obsidian at `~/.loom/vault/` to browse your knowledge base visually.

### Register with Claude Code

Loom ships as a Claude Code plugin. Copy the plugin config to your Claude Code settings:

```bash
# The .claude-plugin/ directory contains:
#   plugin.json    — plugin manifest
#   settings.json  — hook definitions (SessionStart, PostToolUse, Stop)
#   .mcp.json      — MCP server registration
```

Once registered, Loom runs automatically — no manual intervention needed during coding sessions.

## CLI Commands

```bash
loom setup                          # First-time setup wizard
loom config show                    # Print settings (API keys masked)
loom config set <key> <value>       # Update a single setting

loom reindex                        # Incrementally sync vault to ChromaDB
loom reindex --force                # Full re-embed all vault notes
loom reindex --path <file>          # Index a single note

loom graph rebuild                  # Rebuild wikilink graph cache
loom graph neighbors <path>         # Show direct neighbors of a note
loom graph stats                    # Print node/edge counts

loom find-links                     # Discover semantically related notes, queue for review
loom review-links                   # Open browser UI to approve/reject suggested wikilinks
loom review-links --port 8080       # Use a custom port (default: 7842)

loom compress --project <name>      # Run compression for a project
loom compress --project <name> --dry-run  # Preview what would compress

python -m loom                      # Start MCP server (stdio transport)
```

## Packages

This repo contains two packages:

### `loom-claude` (root)

The main Loom plugin — captures Claude Code sessions, stores knowledge in an Obsidian vault, and retrieves context via hybrid vector + graph search.

### `obsidian-mcp` (obsidian-mcp/)

A standalone MCP server for Obsidian via the Obsidian CLI. Usable independently by any MCP-compatible agent — no Loom dependency required. Loom imports `ObsidianCLI` directly as a Python library to avoid MCP protocol overhead for in-process calls.

```bash
# Run as MCP server
obsidian-mcp

# Or use as a library
from obsidian_mcp import ObsidianCLI
```

See [obsidian-mcp/README.md](obsidian-mcp/README.md) for details.

---

## Architecture

### System Overview

```
Claude Code Session
  |
  |--- [SessionStart hook] ---> loom context-hook ---> Load project context
  |                                                     (architecture.md, recent sessions, decisions)
  |
  |--- [PostToolUse hook] ----> loom buffer-event ---> Classify & buffer to SQLite
  |                                                     (file edits, bash commands, decisions)
  |
  |--- [Stop hook] -----------> loom flush ---------> Build session note -> Write to vault
  |                                                     (extract decisions, auto-link wikilinks)
  |
  |--- [MCP tools] -----------> python -m loom -----> loom_search, loom_relate, loom_capture,
                                  (stdio server)        loom_context, loom_compress
```

### Data Flow

```
~/.loom/
  vault/                          <-- Obsidian vault (source of truth)
    projects/{repo}/
      architecture.md             <-- Project architecture notes
      sessions/
        hot/                      <-- Full session notes (0-7 days)
        warm/                     <-- Weekly rollups (7-30 days)
        cold/                     <-- Quarterly digests (30+ days)
      decisions/                  <-- Standalone decision notes (permanent)
    knowledge/
      patterns/                   <-- Auto-extracted patterns
      preferences/                <-- User preferences
      tech/                       <-- Technical knowledge

  index.db                        <-- SQLite (local cache, NOT source of truth)
    pending_events                <-- Event buffer (PostToolUse -> flush)
    pending_writes                <-- Offline write queue (Obsidian down)
    sync_state                    <-- Note-level content hashes for incremental indexing
    chunk_state                   <-- Chunk-level hashes (skip unchanged chunks on reindex)
    note_embeddings               <-- Mean-pooled note vectors (used by semantic link discovery)
    pending_links                 <-- Semantic link suggestions awaiting user review
    graph_cache                   <-- Wikilink adjacency list (manual + approved semantic links)

  chroma/                         <-- ChromaDB vector store (local, zero-config)

  loom-settings.json              <-- Config (mode 600, secrets masked in display)

Ollama (localhost:11434)          <-- Embedding generation (nomic-embed-text, 768-dim)
```

### Module Map

```
loom/
  __main__.py          Entry point: python -m loom (starts MCP server via stdio)
  cli.py               Typer CLI: setup wizard, hooks, reindex, graph, compress
  server.py            FastMCP server: 5 tools + 2 resources
  config.py            Config loader (~/.loom/loom-settings.json)
  db.py                SQLite schema + connection (4 tables)

  capture/             Session capture pipeline
    engine.py          Orchestrator: buffer -> build -> vault write
    buffer.py          SQLite event buffer (insert/load/clear)
    classifier.py      Tool event classification (file_edit, bash_command, decision_signal, skip)
    note_builder.py    Markdown session & decision note assembly with auto-wikilinks

  retrieval/           Hybrid vector + graph search
    embedder.py        Ollama HTTP client (/api/embed) with auto-start recovery
    chunker.py         Semantic + heading-aware chunker (async, content-addressed IDs)
    chroma_store.py    ChromaDB local vector store (upsert/query/delete/get-by-id)
    indexer.py         Scan -> chunk -> embed -> upsert pipeline (chunk-level incremental)
    graph.py           Wikilink graph with BFS traversal (SQLite-backed)
    hybrid.py          3-stage search: vector -> graph expansion -> rerank + on-search link queuing
    semantic_links.py  Pairwise note similarity discovery -> pending_links queue
    context_builder.py Format results for Claude (with token budget)

  ui/                  Local link review web UI
    server.py          FastAPI app: approve/reject semantic link suggestions

  compression/         LSM-tree inspired memory tiering
    scheduler.py       TTL checks, hot->warm and warm->cold transitions
    extractor.py       Decision & pattern extraction from session notes
    summarizer.py      LLM summarization (Ollama by default, Anthropic optional)

  services/            Background service management
    ollama_manager.py  Auto-install, start, model pull for Ollama

  vault/               Obsidian vault access layer
    __init__.py        VaultClient facade (Obsidian CLI -> filesystem fallback)
    filesystem.py      Direct file I/O with path traversal protection
    markdown.py        Frontmatter, wikilink, and tag parsing
    sync.py            Offline write queue flush
```

### Capture Pipeline (Automatic)

Every Claude Code session is captured automatically via hooks:

```
1. SESSION START
   Hook: SessionStart -> loom context-hook
   - Reads JSON from stdin: { session_id, cwd }
   - Derives project name from cwd (repo directory name)
   - Loads architecture.md for the project
   - Loads last 3 hot session notes (500 char excerpts)
   - Lists decision note wikilinks
   - Checks if sessions are ready for compression
   - Prints context markdown to stdout -> injected into Claude's context

2. DURING SESSION (every tool call)
   Hook: PostToolUse -> loom buffer-event
   - Reads JSON from stdin: { session_id, tool_name, tool_input, tool_response }
   - Classifier categorizes the event:
     * file_edit    — Write, Edit, NotebookEdit
     * bash_command — Bash (filtered: skips ls, pwd, cd, etc.)
     * decision_signal — any tool where input/response contains
                         "decided", "chose", "trade-off", "because", "instead of"
     * skip — Read, Glob, Grep, WebSearch (read-only, no capture needed)
   - Non-skip events stored in SQLite pending_events table
   - Always exits 0 (never blocks Claude Code)

3. SESSION END
   Hook: Stop -> loom flush
   - Reads JSON from stdin: { session_id, cwd }
   - Loads all pending_events for this session from SQLite
   - Groups events by category (file edits, commands, decisions)
   - Deduplicates file paths and commands

   Build session note (note_builder.py):
   - YAML frontmatter: type: session, project, date, tags
   - Summary paragraph: "Edited N files, ran M commands, made K decisions"
   - Sections: ## Key Decisions, ## Files Changed, ## Commands Run, ## Errors
   - Auto-wikilinks: scans vault for existing note titles,
     wraps first occurrence of each in [[path|title]]
   - Writes to: projects/{project}/sessions/hot/{date}.md

   Extract decisions (note_builder.py):
   - Parses decision_signal events
   - Each becomes standalone note: projects/{project}/decisions/{slug}.md
   - Avoids duplicates by checking existing decision slugs

   Vault write (VaultClient):
   - If Obsidian CLI is online: writes via CLI
   - If offline: writes to filesystem + queues in pending_writes table
   - On reconnect: flush_pending_writes() replays queued writes

   Cleanup:
   - Clears pending_events for this session from SQLite
```

### Retrieval Pipeline (On-Demand)

When Claude calls `loom_search`, the hybrid retrieval engine runs a 3-stage pipeline:

```
STAGE 1: Vector Search
  - Embed query text via Ollama (nomic-embed-text, 768-dim)
  - Query ChromaDB: cosine similarity, optional project filter
  - Returns top-K results with scores + metadata

STAGE 2: Graph Expansion
  - For each vector hit, BFS the wikilink graph (depth 2)
  - Collect neighbor notes not already in results
  - Read note content from vault for excerpts

STAGE 3: Rerank & Merge
  - Combined score = 0.6 * vector_score + 0.4 * (1 / graph_hops)
  - Direct vector hits: score = vector_score
  - Graph-only hits: score = 0.4 * (1 / hops)
  - Sort by combined score descending
  - Return top-limit results with path, score, source, excerpt
```

The indexing pipeline that feeds vector search:

```
loom reindex (cli.py -> indexer.py)
  1. Scan ~/.loom/vault/ for all .md files
  2. For each file:
     a. SHA256 hash of content
     b. Check sync_state — skip note entirely if hash unchanged
     c. Parse note (frontmatter, wikilinks, tags)
     d. Semantic chunking (chunker.py):
        - Split at heading boundaries, tracking full breadcrumb path
        - Within each section: embed paragraphs via Ollama, find semantic
          breakpoints where similarity drops > threshold (default 0.15)
        - Each chunk prefixed with heading breadcrumb (e.g. "## Arch > ### DB")
        - Content-addressed ID: {path}#{sha256(chunk_text)[:8]}
        - First chunk per section = "parent"; subsequent = "children" with parent_chunk_id
     e. Chunk-level incremental check (chunk_state table):
        - Skip embedding chunks whose text hash is unchanged
        - Only delete removed chunk IDs from ChromaDB (not whole note)
        - Only embed + upsert new/changed chunks
     f. Mean-pool all chunk vectors -> store in note_embeddings (for link discovery)
     g. Update sync_state and chunk_state hashes
  3. Remove vectors and state entries for deleted notes
```

Semantic link discovery pipeline:

```
loom find-links (cli.py -> semantic_links.py)
  1. Load all note_embeddings from SQLite (mean-pooled vectors)
  2. L2-normalise all vectors, compute pairwise cosine similarity
  3. For each note: collect top-K neighbours above threshold (default 0.82)
  4. Filter pairs already in graph_cache or pending_links
  5. Insert candidates into pending_links with similarity score + excerpt

loom review-links (cli.py -> ui/server.py)
  - Starts FastAPI server at localhost:7842
  - Browser UI shows: source note | similarity score | target note
  - Approve: writes [[wikilink]] to source note via VaultClient,
             updates graph_cache (now traversable by hybrid_search BFS)
  - Reject: marks suggestion as rejected in pending_links
  - "Find new links" button: triggers discovery inline
```

### Compression Pipeline (Opt-In)

Loom uses LSM-tree inspired tiering to keep the vault useful as it grows:

```
TIER        AGE         CONTENT                INDEXED
hot         0-7 days    Full session notes     Full vectors in ChromaDB
  |
  | [hot_ttl_days elapsed, loom compress triggered]
  v
warm        7-30 days   Weekly rollups         Summarized vectors
  |
  | [warm_ttl_days elapsed]
  v
cold        30+ days    Quarterly digests      Digest vectors + architecture.md append
permanent   forever     decisions/, knowledge/ Never compressed
```

Hot -> Warm compression:
1. Load all hot sessions past `hot_ttl_days` for a project
2. Extract decisions -> standalone notes in decisions/
3. Extract patterns -> frequency analysis of modified files
4. Call configured LLM (Ollama by default, Anthropic optional) with combined session text
5. Write rollup to sessions/warm/{iso-week}.md
6. Frontmatter: `type: rollup, source_sessions: [...]`

Warm -> Cold compression:
1. Load all warm rollups past `warm_ttl_days`
2. Call configured LLM with combined rollup text
3. Write digest to sessions/cold/{quarter}.md
4. Append digest summary to architecture.md
5. Frontmatter: `type: digest, source_rollups: [...]`

### MCP Server

The MCP server (`python -m loom`) exposes 5 tools and 2 resources over stdio transport:

| Tool | Trigger | What it does |
|---|---|---|
| `loom_context` | SessionStart | Load architecture.md + recent sessions + decisions for a project |
| `loom_capture` | On-demand | Write a session or decision note to the vault |
| `loom_search` | On-demand | Hybrid vector + graph search across the vault |
| `loom_relate` | On-demand | BFS the wikilink graph from a seed note |
| `loom_compress` | On-demand | Check or trigger compression for a project |

| Resource | URI | Returns |
|---|---|---|
| Project context | `loom://project/{repo}` | architecture.md content |
| Preferences | `loom://knowledge/preferences` | All preference notes |

### SQLite Schema

Seven tables in `~/.loom/index.db` (local cache only, vault is source of truth):

```sql
-- Note-level content hashes for incremental reindex
CREATE TABLE sync_state (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    indexed_at TIMESTAMP NOT NULL
);

-- Chunk-level content hashes: skip re-embedding unchanged chunks within a changed note
CREATE TABLE chunk_state (
    chunk_id   TEXT PRIMARY KEY,  -- {note_path}#{sha256(text)[:8]}
    note_path  TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    indexed_at TIMESTAMP NOT NULL
);

-- Mean-pooled note embedding (average of chunk vectors) for pairwise link discovery
CREATE TABLE note_embeddings (
    note_path  TEXT PRIMARY KEY,
    embedding  BLOB NOT NULL,     -- packed IEEE 754 doubles
    indexed_at TIMESTAMP NOT NULL
);

-- Semantic link candidates awaiting user approval via loom review-links
CREATE TABLE pending_links (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path    TEXT NOT NULL,
    target_path    TEXT NOT NULL,
    similarity     REAL NOT NULL,
    source_excerpt TEXT,
    target_excerpt TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at     TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_path, target_path)
);

-- Buffers vault writes when Obsidian is offline (FIFO replay on reconnect)
CREATE TABLE pending_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_path TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wikilink adjacency list for BFS graph traversal (manual + approved semantic links)
CREATE TABLE graph_cache (
    from_path TEXT NOT NULL,
    to_path TEXT NOT NULL,
    PRIMARY KEY (from_path, to_path)
);

-- Session event buffer (PostToolUse hook -> Stop hook flush)
CREATE TABLE pending_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT NOT NULL,
    tool_response TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Configuration

Config lives at `~/.loom/loom-settings.json` (file mode 600):

```json
{
  "vault_path": "~/.loom/vault",
  "chroma_path": "~/.loom/chroma",
  "obsidian": {
    "vault_name": "loom"
  },
  "embedding": {
    "provider": "ollama",
    "model": "nomic-embed-text",
    "dimensions": 768,
    "ollama_base_url": "http://localhost:11434"
  },
  "compression": {
    "enabled": false,
    "require_user_approval": true,
    "llm_provider": "ollama",
    "llm_model": "llama3.2",
    "anthropic_api_key": "",
    "hot_ttl_days": 7,
    "warm_ttl_days": 30
  },
  "semantic_links": {
    "enabled": true,
    "similarity_threshold": 0.82,
    "max_links_per_note": 5,
    "auto_on_search": false,
    "semantic_chunking_threshold": 0.15
  }
}
```

`compression` settings:

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable/disable the compression pipeline |
| `require_user_approval` | `true` | Notify Claude before compressing; user must confirm |
| `llm_provider` | `"ollama"` | LLM used for summarization: `"ollama"` or `"anthropic"` |
| `llm_model` | `"llama3.2"` | Chat model to use (e.g. `llama3.2`, `mistral`, `claude-haiku-4-5-20251001`) |
| `anthropic_api_key` | `""` | Only required when `llm_provider` is `"anthropic"` |
| `hot_ttl_days` | `7` | Days before hot sessions are eligible for warm rollup |
| `warm_ttl_days` | `30` | Days before warm rollups are eligible for cold digest |

To use Anthropic instead of Ollama for compression:
```bash
loom config set compression_llm_provider anthropic
loom config set compression_llm_model claude-haiku-4-5-20251001
loom config set compression_anthropic_key sk-ant-...
```

`semantic_links` settings:

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Enable/disable all semantic link features |
| `similarity_threshold` | `0.82` | Minimum cosine similarity to queue a link candidate |
| `max_links_per_note` | `5` | Max new link candidates per source note per run |
| `auto_on_search` | `false` | Queue link candidates automatically during `loom_search` calls |
| `semantic_chunking_threshold` | `0.15` | Relative similarity drop that triggers a semantic chunk boundary |

### Key Design Decisions

| Decision | Rationale |
|---|---|
| Ollama as hard dependency | Avoids API costs for embeddings; local privacy; clear failure > silent fallback |
| Separate `~/.loom/vault/` | Avoids polluting user's existing Obsidian vault |
| ChromaDB (local) | Zero-config setup; no external accounts; privacy-first |
| SQLite as local cache only | Vault markdown is source of truth, not the database |
| Compression opt-in | User data safety; compression is irreversible without archive |
| MCP stdio (not HTTP) | No external ports opened; standard MCP transport |
| Direct ObsidianCLI import | Avoids MCP serialization overhead for in-process vault access |
| Semantic chunking (async, Ollama-guided) | Chunks split at meaning changes, not character counts; heading breadcrumbs preserve context for retrieval |
| Content-addressed chunk IDs | `{path}#{sha256(text)[:8]}` — chunk IDs stable across edits; enables chunk-level skip during reindex |
| Mean-pooled note embedding in SQLite | Single representative vector per note enables fast pairwise similarity without re-querying ChromaDB |
| User-approval for semantic links | Auto-discovered wikilinks are queued as pending, never written without `loom review-links` approval |

## Development

```bash
uv sync                    # Install all dependencies
uv run pytest              # Run tests
uv run mypy loom/          # Type check
uv run ruff check loom/    # Lint
```

Tests mirror source structure: `tests/capture/test_classifier.py` tests `loom/capture/classifier.py`.

## License

MIT

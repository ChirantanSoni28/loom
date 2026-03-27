# Loom — Vision & Architecture

> Weaving knowledge across Claude Code sessions via an Obsidian-backed graph retrieval system.

---

## Problem

Claude Code starts cold every session. No memory of past decisions, patterns, architecture choices, or debugging history. Every session re-explains the same context. This wastes time and produces lower-quality outputs.

## Solution

**Loom** is a Claude Code plugin that automatically captures session knowledge into an Obsidian vault and retrieves relevant context on-demand using hybrid graph + semantic search. Obsidian is the human-editable source of truth — your second brain for every project you work on with Claude Code.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| MCP Server | `mcp` official Python SDK (stdio transport) |
| Vector Store | Pinecone (cloud, shared across machines) |
| Embeddings | Ollama `nomic-embed-text` (local, **configurable**) |
| Vault Access | obsidian-local-rest-api (HTTPS REST) |
| Graph Cache | SQLite (`~/.loom/index.db`) |
| LLM Compression | Claude API `claude-haiku-4-5` (opt-in, user-controlled) |
| Config | `~/.loom/loom-settings.json` |

---

## Directory Layout (Runtime)

```
~/.loom/
  vault/                        ← Obsidian vault (local-first; optionally synced via Obsidian Sync)
    projects/
      {repo-name}/
        sessions/
          hot/                  ← 0-7 days, full session detail
          warm/                 ← 7-30 days, weekly rollups
          cold/                 ← 30+ days, quarterly digests
        decisions/              ← extracted architecture decision records
        architecture.md         ← auto-maintained project overview
    knowledge/
      patterns/                 ← cross-project code patterns
      preferences/              ← user style & preferences
      tech/                     ← notes on libs/frameworks
  index.db                      ← SQLite: graph cache + sync state + pending writes
  loom-settings.json            ← all config (API keys, feature flags, embedding model)
```

---

## `loom-settings.json` Structure

```json
{
  "vault_path": "~/.loom/vault",
  "obsidian": {
    "rest_api_key": "YOUR_KEY",
    "rest_api_port": 27123
  },
  "embedding": {
    "provider": "ollama",
    "model": "nomic-embed-text",
    "dimensions": 768,
    "ollama_base_url": "http://localhost:11434"
  },
  "pinecone": {
    "api_key": "YOUR_KEY",
    "index_name": "loom-vault"
  },
  "compression": {
    "enabled": false,
    "require_user_approval": true,
    "anthropic_api_key": "YOUR_KEY",
    "hot_ttl_days": 7,
    "warm_ttl_days": 30
  }
}
```

**Embedding model is configurable** — change `embedding.model` + `embedding.dimensions`, then run `loom reindex` to re-embed the vault into Pinecone.

---

## Architecture Diagram

```
┌───────────────────────────────────────────────────────────┐
│                      CLAUDE CODE                           │
│                                                            │
│  SessionStart → loom_context   (load project context)     │
│  PostToolUse  → buffer events  (auto-capture)             │
│  Stop         → loom_capture   (write session note)       │
│                                                            │
│  MCP tools: loom_search  loom_capture  loom_context       │
│             loom_relate  loom_compress                    │
└──────────────────────┬─────────────────────────────────────┘
                       │ stdio
┌──────────────────────▼─────────────────────────────────────┐
│           LOOM MCP SERVER (Python 3.12+)                   │
│                                                            │
│  Capture Engine      Retrieval Engine    Compression       │
│  ─────────────       ────────────────   ──────────────    │
│  classify event      1. Pinecone vec    hot→warm rollup    │
│  extract decisions   2. graph BFS       warm→cold digest   │
│  build note          3. rerank+merge    user approval      │
│  write to vault                         opt-in only        │
└──────────────┬───────────────┬────────────────────────────┘
               │               │
   ┌───────────▼───┐   ┌───────▼──────────────────────────┐
   │  OBSIDIAN     │   │  LOCAL SQLite + Pinecone          │
   │  REST API     │   │                                   │
   │               │   │  graph cache (wikilinks adj)      │
   │  ~/.loom/     │   │  sync state  (file hashes)        │
   │  vault/       │   │  pending_writes (offline queue)   │
   │               │   │  Pinecone: 768-dim vectors        │
   └───────────────┘   └───────────────────────────────────┘
```

---

## Retrieval Pipeline

Three-stage hybrid retrieval on every query:

```
1. VECTOR SEARCH (fast, semantic)
   Query → Ollama embed → Pinecone cosine similarity
   Filtered by project + tier metadata
   → top-K candidates

2. GRAPH TRAVERSAL (relationship-aware)
   For each Stage 1 hit: BFS via Obsidian wikilinks (depth 2)
   Collect neighbor notes across project + knowledge scopes
   → expanded candidate set

3. RERANK + MERGE
   Score = 0.6 × vector_score + 0.4 × (1 / graph_distance)
   Deduplicate, truncate to ~4000 token budget
   → context with citations returned to Claude
```

---

## Compression Model

Inspired by: LSM-tree compaction + GraphRAG community summaries + MemGPT tiered memory.

```
HOT    (0-7 days)    Full session notes. Fully indexed in Pinecone.
WARM   (7-30 days)   Weekly rollups. Key decisions extracted first.
COLD   (30+ days)    Quarterly digests. Merged into architecture.md.
PERMANENT            decisions/ + knowledge/ — never compressed.
```

- **Default: compression OFF** (`enabled: false`)
- When `require_user_approval: true`: Claude asks before each compression run
- Decisions and patterns always extracted to permanent storage before compressing

---

## Multi-Machine Support

- `~/.loom/vault/` syncs via **Obsidian Sync** (user opt-in) — all notes available everywhere
- `~/.loom/loom-settings.json` configured per-machine (API keys stay local)
- Pinecone index is shared — all machines read/write the same index
- Ollama runs locally on each machine (hard dependency)

---

## Installation

```bash
claude plugin install chirantansoni/loom
loom setup    # interactive wizard
```

---

## Feature Roadmap

| # | Feature | Status |
|---|---------|--------|
| F01 | [Project Scaffold + Setup Wizard](features/F01-scaffold-setup.md) | complete |
| F02 | [Obsidian Vault Integration](features/F02-obsidian-vault.md) | complete |
| F03 | [MCP Server Core](features/F03-mcp-server.md) | pending |
| F04 | [Capture Engine + Hooks](features/F04-capture-hooks.md) | pending |
| F05 | [Vector Indexing — Pinecone + Ollama](features/F05-vector-indexing.md) | pending |
| F06 | [Graph Traversal — Wikilink Graph](features/F06-graph-traversal.md) | pending |
| F07 | [Hybrid Retrieval Engine](features/F07-hybrid-retrieval.md) | pending |
| F08 | [Compression Scheduler](features/F08-compression.md) | pending |
| F09 | [Plugin Packaging + Open Source Release](features/F09-packaging.md) | pending |

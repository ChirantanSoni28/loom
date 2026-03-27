# F08: Compression Scheduler

**Status:** pending
**Depends on:** F04 (session notes in vault), F03 (MCP server), F01 (loom-settings.json)
**Review gate:** With compression enabled + approval required, Claude asks user before rolling up hot sessions; rollup note appears in warm/; decisions extracted to decisions/

---

## Goal

Implement the three-tier compression pipeline (hot → warm → cold) with user-controlled approval. Compression is disabled by default. When enabled, it runs checks at `SessionStart` and notifies Claude if sessions are ready to compress — Claude then asks the user before proceeding. Timeless decisions and patterns are always extracted before compressing.

---

## Files

```
loom/
  compression/
    scheduler.py     ← check tiers, determine what's ready to compress
    summarizer.py    ← LLM-based rollup using Claude API
    extractor.py     ← extract decisions + patterns before compressing
    __init__.py
```

---

## Compression Tiers

```
HOT    ~/.loom/vault/projects/{repo}/sessions/hot/
       Notes newer than hot_ttl_days (default: 7).
       Full detail, fully indexed.

WARM   ~/.loom/vault/projects/{repo}/sessions/warm/
       Weekly rollup notes (one per week).
       Created when hot/ notes exceed hot_ttl_days.

COLD   ~/.loom/vault/projects/{repo}/sessions/cold/
       Quarterly digest notes.
       Created when warm/ notes exceed warm_ttl_days (default: 30).
```

**Permanent (never compressed):**
```
~/.loom/vault/projects/{repo}/decisions/
~/.loom/vault/knowledge/
~/.loom/vault/projects/{repo}/architecture.md
```

---

## `scheduler.py` — Compression Check

```python
@dataclass
class CompressionReport:
    project: str
    hot_ready: list[str]       # paths of hot sessions past TTL
    warm_ready: list[str]      # paths of warm rollups past TTL
    can_compress: bool         # False if compression disabled in settings
    requires_approval: bool    # from loom-settings.json

async def check_compression(project: str, config: LoomConfig, vault_client: VaultClient) -> CompressionReport:
    """
    Called at SessionStart.
    Checks hot/ and warm/ for notes past their TTL.
    Returns report without compressing anything yet.
    """

async def run_hot_to_warm(project: str, hot_paths: list[str], config: LoomConfig, ...) -> str:
    """
    1. Call extractor: extract decisions from hot sessions → write to decisions/
    2. Call summarizer: LLM weekly rollup → write to warm/{week}.md
    3. Move hot sessions to warm/ (rename path)
    4. Trigger reindex for new warm note
    Returns path of new warm rollup note.
    """

async def run_warm_to_cold(project: str, warm_paths: list[str], config: LoomConfig, ...) -> str:
    """
    1. Call extractor: extract any remaining patterns
    2. Call summarizer: LLM quarterly digest → write to cold/{quarter}.md
    3. Update architecture.md with digest summary
    4. Move warm notes to cold/
    Returns path of new cold digest note.
    """
```

---

## `summarizer.py` — LLM Rollup

Uses Claude API (`claude-haiku-4-5`) to summarize session batches:

```python
async def summarize_hot_to_warm(
    sessions: list[str],   # list of session note contents
    project: str,
    week: str,             # e.g. "2026-W13"
    anthropic_key: str,
) -> str:
    """
    Prompt instructs Claude to:
    - Summarize the week's sessions in 200-400 words
    - Highlight key decisions (with wikilinks preserved)
    - Note any patterns observed
    - List files changed (deduplicated)
    Returns markdown string for the warm rollup note.
    """

async def summarize_warm_to_cold(
    rollups: list[str],    # list of warm rollup note contents
    project: str,
    quarter: str,          # e.g. "2026-Q1"
    anthropic_key: str,
) -> str:
    """
    Creates a quarterly digest: major themes, key decisions, architectural changes.
    Returns markdown string for the cold digest note.
    """
```

---

## `extractor.py` — Pre-Compression Extraction

Before any compression, extract timeless content to permanent storage:

```python
async def extract_decisions(session_contents: list[str], project: str, vault_client: VaultClient) -> list[str]:
    """
    Scan session notes for "Key Decisions" sections.
    For each decision not already in decisions/:
      - Create decisions/{slug}.md with proper frontmatter
      - Return list of created paths
    """

async def extract_patterns(session_contents: list[str], vault_client: VaultClient) -> list[str]:
    """
    Detect recurring patterns across multiple sessions (same file/tool/approach used repeatedly).
    Write to knowledge/patterns/{slug}.md.
    Return list of created paths.
    """
```

---

## User Approval Flow

When `require_user_approval: true` (default), compression is surfaced to the user via the MCP server:

**At `SessionStart`**, after loading context, the scheduler check runs. If sessions are ready:

```python
# MCP server surfaces this as a notification appended to loom_context output:

"""
---
⚡ Loom: 5 sessions from last week are ready to compress into a weekly rollup.
   Run `loom_compress` tool to proceed, or ignore to keep sessions as-is.
   (Disable this check: set compression.enabled=false in loom-settings.json)
"""
```

Claude then surfaces this to the user naturally in conversation. The user says "yes compress" or "not now."

**`loom_compress` tool (from F03 stub, now functional):**
```python
@server.tool()
async def loom_compress(project: str, dry_run: bool = False) -> dict:
    report = await check_compression(project, config, vault_client)
    if dry_run:
        return {"hot_ready": len(report.hot_ready), "warm_ready": len(report.warm_ready), "status": "dry_run"}
    # Run actual compression
    warm_path = await run_hot_to_warm(project, report.hot_ready, ...)
    return {"compressed": len(report.hot_ready), "rollup": warm_path, "status": "done"}
```

---

## `loom compress` CLI Commands

| Command | Description |
|---------|-------------|
| `loom compress --project my-repo` | Run compression for a project |
| `loom compress --dry-run` | Show what would be compressed |
| `loom compress --all` | Compress all projects |

---

## Acceptance Criteria

- [ ] With `compression.enabled: false`: no compression runs, no notifications shown
- [ ] With `compression.enabled: true, require_user_approval: true`: notification shown at session start when sessions are past TTL
- [ ] `loom_compress` (MCP tool): runs hot→warm compression, produces rollup note in warm/
- [ ] Decisions extracted to `decisions/` before hot notes are moved
- [ ] Warm rollup note is a coherent LLM-generated summary of the week's sessions
- [ ] Rollup note preserves wikilinks from source sessions
- [ ] Rollup note is immediately indexed in Pinecone (via indexer)
- [ ] With `require_user_approval: false`: compression runs silently at session start
- [ ] `loom compress --dry-run` shows count without writing anything
- [ ] architecture.md updated when warm→cold compression runs

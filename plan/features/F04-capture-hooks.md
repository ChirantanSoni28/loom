# F04: Capture Engine + Hooks

**Status:** pending
**Depends on:** F02 (VaultClient), F03 (MCP server running)
**Review gate:** End a Claude Code session, verify session note appears in `~/.loom/vault/projects/{repo}/sessions/hot/`

---

## Goal

Wire up Claude Code hooks so that Loom automatically captures every session. The `PostToolUse` hook buffers tool events during a session; the `Stop` hook flushes the buffer into a structured session note written to the vault. Decisions detected in the buffer are extracted as separate decision notes. No manual intervention needed.

---

## Files

```
loom/
  capture/
    engine.py        ← main capture orchestrator
    classifier.py    ← classify events: decision vs file-change vs error
    buffer.py        ← in-memory + SQLite-backed event buffer
    note_builder.py  ← assemble structured markdown note from buffer
    __init__.py
  cli.py             ← new commands: `loom buffer-event`, `loom flush`
```

`.claude-plugin/settings.json` (updated):
```json
{
  "hooks": {
    "SessionStart": [{
      "type": "command",
      "command": "python -m loom context-hook"
    }],
    "PostToolUse": [{
      "type": "command",
      "command": "python -m loom buffer-event"
    }],
    "Stop": [{
      "type": "command",
      "command": "python -m loom flush"
    }]
  }
}
```

---

## Hook Data Flow

### `SessionStart` → `loom context-hook`
```
stdin: { "session_id": "...", "cwd": "/path/to/repo" }

Action:
  1. Detect project name from cwd (git repo name or dirname)
  2. Call loom_context MCP tool to load project notes
  3. Print context to stdout (injected into Claude's context window)

stdout: project context markdown (displayed to Claude at session start)
```

### `PostToolUse` → `loom buffer-event`
```
stdin: {
  "tool_name": "Write",
  "tool_input": { "file_path": "...", "content": "..." },
  "tool_response": { "success": true },
  "session_id": "..."
}

Action:
  1. Parse event
  2. Classify (see classifier.py)
  3. Append to buffer (SQLite: pending_events table, keyed by session_id)

exit code: 0 (always proceed — never block tool execution)
```

### `Stop` → `loom flush`
```
stdin: { "session_id": "...", "cwd": "/path/to/repo" }

Action:
  1. Load all buffered events for this session_id
  2. Build session note (note_builder.py)
  3. Extract decisions from buffer
  4. Write session note → vault sessions/hot/{date}-{repo}.md
  5. Write each decision → vault decisions/{slug}.md
  6. Auto-link: scan note for entities that match existing vault notes → add [[wikilinks]]
  7. Update architecture.md (append new facts section)
  8. Clear buffer for this session_id

exit code: 0
```

---

## `classifier.py` — Event Classification

```python
EventType = Literal["file_edit", "bash_command", "decision_signal", "error_resolution", "skip"]

def classify_event(tool_name: str, tool_input: dict, tool_response: dict) -> EventType:
    """
    file_edit:        Write, Edit tools
    bash_command:     Bash tool (filtered — skip trivial commands)
    decision_signal:  tool_input or tool_response contains decision keywords
                      ("decided", "chose", "instead of", "because", "trade-off")
    error_resolution: prior tool failed, this tool succeeded on same resource
    skip:             Read tool, Glob, Grep, TodoRead — informational, not captured
    """
```

---

## `note_builder.py` — Session Note Assembly

Assembles structured markdown from the event buffer:

```python
def build_session_note(
    events: list[BufferedEvent],
    project: str,
    date: str,
    repo_path: str,
) -> str:
    """
    Returns a markdown string with frontmatter + sections:
    - Summary (auto-generated from event list)
    - Key Decisions (decision_signal events)
    - Files Changed (file_edit events, deduplicated)
    - Commands Run (bash_command events, filtered)
    - Errors Resolved (error_resolution events)
    """
```

---

## `buffer.py` — Event Buffer

Events are persisted in SQLite so they survive crashes:

```sql
CREATE TABLE IF NOT EXISTS pending_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    tool_input  TEXT NOT NULL,   -- JSON
    tool_response TEXT NOT NULL, -- JSON
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```python
def buffer_event(session_id: str, event: RawEvent) -> None
def load_events(session_id: str) -> list[BufferedEvent]
def clear_events(session_id: str) -> None
```

---

## Auto-Linking Logic

After building the note, scan for vault entity matches:
1. Load all existing note titles from `~/.loom/vault/` (cached, refreshed on session start)
2. For each title that appears verbatim in the session note body → wrap in `[[title]]`
3. Add matched links to frontmatter `related:` array

This keeps the wikilink graph growing naturally without manual effort.

---

## New SQLite Table

```sql
CREATE TABLE IF NOT EXISTS pending_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    tool_input  TEXT NOT NULL,
    tool_response TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Acceptance Criteria

- [ ] `PostToolUse` hook fires on every tool use, buffers event without blocking Claude
- [ ] `Stop` hook fires at session end, produces a session note in `sessions/hot/`
- [ ] Decision signals (keywords detected) produce separate notes in `decisions/`
- [ ] File edits are deduplicated in the "Files Changed" section
- [ ] `skip` events (Read, Glob, Grep) are not included in the session note
- [ ] Auto-linking correctly wraps known vault note titles in `[[wikilinks]]`
- [ ] Buffer survives crash: if session_id events exist in SQLite, `loom flush` can replay them
- [ ] `loom flush --session-id <id>` works manually for debugging

# F06: Graph Traversal — Wikilink Graph

**Status:** pending
**Depends on:** F02 (markdown parser, vault access), F01 (SQLite)
**Review gate:** `loom_relate` returns correct neighbors; graph BFS from a seed note returns related notes up to depth 2

---

## Goal

Build the graph layer: parse wikilinks from all vault notes, store as an adjacency list in SQLite, and expose BFS traversal for relationship-aware retrieval. After this feature, `loom_relate` is fully functional and the retrieval pipeline (F07) can expand vector search hits via graph neighbors.

---

## Files

```
loom/
  retrieval/
    graph.py         ← build adjacency list, BFS traversal, graph cache
```

---

## Graph Model

Obsidian's `[[wikilinks]]` are directed edges. Loom uses **undirected** traversal (both forward-links and backlinks) to surface related notes.

```
Node:  vault note path (e.g. "projects/my-repo/decisions/auth-jwt.md")
Edge:  [[wikilink]] from note A → note B
```

**SQLite graph_cache table** (from F01 schema):
```sql
CREATE TABLE IF NOT EXISTS graph_cache (
    from_path   TEXT NOT NULL,
    to_path     TEXT NOT NULL,
    PRIMARY KEY (from_path, to_path)
);
```

---

## `graph.py` Interface

```python
class VaultGraph:
    def __init__(self, db: Connection):
        self.db = db

    async def rebuild(self, vault_client: VaultClient) -> int:
        """
        Scan all .md files in vault, parse wikilinks, rebuild graph_cache.
        Returns count of edges written.
        Called on:
          - `loom reindex` (full rebuild)
          - After each new note is written (incremental: add edges for new note only)
        """

    def neighbors(self, path: str, direction: str = "both") -> list[str]:
        """
        direction: "out" (forward links), "in" (backlinks), "both"
        Returns direct neighbors (depth 1).
        """

    def bfs(self, seed_paths: list[str], max_depth: int = 2) -> list[GraphNode]:
        """
        BFS from one or more seed nodes up to max_depth.
        Returns list of GraphNode(path, hops) sorted by hops ascending.
        Deduplicates nodes. Does not return seed_paths themselves.
        """

    def add_note_edges(self, path: str, wikilinks: list[str]) -> None:
        """Incremental update: add edges for a single newly-written note."""

    def remove_note_edges(self, path: str) -> None:
        """Remove all edges for a deleted note."""


@dataclass
class GraphNode:
    path: str
    hops: int
    direction: str   # "forward", "backward", "both"
```

---

## Graph Build Flow

```
rebuild():
  1. List all .md files in vault (filesystem walk)
  2. For each file:
       parsed = parse_note(content)
       for wikilink in parsed.wikilinks:
           resolved_path = resolve_wikilink(wikilink, vault_path)
           INSERT OR IGNORE INTO graph_cache (from_path, to_path)
  3. Clean stale edges (paths no longer in vault)
```

**Wikilink resolution:**
- `[[note title]]` → search vault for a note whose filename matches (case-insensitive)
- `[[folder/note]]` → direct path lookup
- Unresolved links are stored as-is (do not fail; vault may not have the note yet)

---

## BFS Traversal Example

```
Vault graph:
  auth-jwt.md  →  [[jwt-patterns]]  →  jwt-patterns.md
  auth-jwt.md  ←  [[auth-jwt]]      ←  architecture.md

Query: bfs(["auth-jwt.md"], max_depth=2)

Result:
  GraphNode("jwt-patterns.md", hops=1, direction="forward")
  GraphNode("architecture.md", hops=1, direction="backward")
  GraphNode("knowledge/tech/jwt.md", hops=2, direction="forward")
```

---

## Integration with `loom_relate` (upgrade from F03 stub)

```python
async def loom_relate(path: str, depth: int = 2) -> list[dict]:
    graph = VaultGraph(db)
    nodes = graph.bfs([path], max_depth=depth)
    return [{"path": n.path, "hops": n.hops} for n in nodes]
```

---

## `loom graph` CLI Commands

| Command | Description |
|---------|-------------|
| `loom graph rebuild` | Full graph rebuild from vault |
| `loom graph neighbors <path>` | Show direct neighbors of a note |
| `loom graph stats` | Print node/edge counts |

---

## Acceptance Criteria

- [ ] `graph.rebuild()` correctly parses all `[[wikilinks]]` from vault notes
- [ ] `graph.bfs(["path"], max_depth=2)` returns correct neighbors with hop counts
- [ ] `loom_relate` returns graph neighbors (not empty list as in F03 stub)
- [ ] Forward links and backlinks both returned by `direction="both"`
- [ ] New note written by capture engine: `add_note_edges()` called immediately (no full rebuild needed)
- [ ] Unresolved wikilinks (targets not in vault) stored without error
- [ ] `loom graph rebuild` completes on a vault with 100+ notes in under 5 seconds
- [ ] `loom graph neighbors <path>` prints correct neighbors from CLI

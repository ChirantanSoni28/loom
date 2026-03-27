# F07: Hybrid Retrieval Engine

**Status:** pending
**Depends on:** F05 (vector search), F06 (graph traversal)
**Review gate:** `loom_search "auth decisions"` returns results that combine semantic matches + graph-expanded neighbors, with correct ranking

---

## Goal

Wire together the vector search (F05) and graph traversal (F06) into a unified retrieval pipeline. Results are merged, reranked by a combined score, and truncated to fit Claude's context budget. After this feature, `loom_search` and `loom_context` deliver the full hybrid experience.

---

## Files

```
loom/
  retrieval/
    hybrid.py        ← merge + rerank pipeline
    context_builder.py ← format results into Claude-friendly context
```

---

## Retrieval Pipeline (3 Stages)

### Stage 1 — Vector Search (Pinecone)
```python
embedding = await embedder.embed(query)
vector_hits = await pinecone_store.query(
    embedding,
    top_k=top_k * 2,           # fetch extra to allow graph expansion
    filter={"project": project} if project else None
)
# Returns: list[SearchResult(path, score, excerpt, metadata)]
```

### Stage 2 — Graph Expansion (BFS)
```python
seed_paths = [r.path for r in vector_hits]
graph_nodes = graph.bfs(seed_paths, max_depth=2)

# Load content for each graph neighbor not already in vector_hits
expanded = []
for node in graph_nodes:
    if node.path not in seen_paths:
        content = await vault_client.read_note(node.path)
        expanded.append(SearchResult(
            path=node.path,
            score=0.0,           # no vector score; scored by graph distance
            graph_hops=node.hops,
            excerpt=content[:500],
            metadata={...}
        ))
```

### Stage 3 — Rerank + Merge
```python
def combined_score(result: SearchResult) -> float:
    vector_component = result.score * 0.6
    graph_component = (1 / result.graph_hops) * 0.4 if result.graph_hops > 0 else 0
    return vector_component + graph_component

all_results = vector_hits + expanded
all_results.sort(key=combined_score, reverse=True)
all_results = deduplicate(all_results)          # keep highest score per path
all_results = all_results[:limit]
```

---

## `hybrid.py` Interface

```python
@dataclass
class SearchResult:
    path: str
    score: float              # combined score
    vector_score: float       # raw Pinecone score (0 if graph-only)
    graph_hops: int           # 0 if from vector search, 1+ if from graph expansion
    excerpt: str
    metadata: dict

async def hybrid_search(
    query: str,
    config: LoomConfig,
    db: Connection,
    vault_client: VaultClient,
    project: str | None = None,
    limit: int = 5,
    top_k: int = 20,
) -> list[SearchResult]:
    """Full 3-stage hybrid retrieval pipeline."""
```

---

## `context_builder.py` — Format for Claude

Converts search results into Claude-readable context with citations:

```python
def build_context(results: list[SearchResult], token_budget: int = 4000) -> str:
    """
    Returns markdown string:

    ## Relevant Context from Vault

    ### [1] projects/my-repo/decisions/auth-jwt.md (score: 0.91)
    > [excerpt of note content, truncated to fit budget]
    > *Tags: auth, jwt | Type: decision*

    ### [2] knowledge/patterns/jwt-refresh.md (score: 0.78, via graph)
    > [excerpt]

    [N results | ~1240 tokens]
    """
```

Token budget enforcement:
- Estimate tokens as `len(text) / 4`
- Fill results in score order until budget exhausted
- Always include at least 1 result even if over budget

---

## Updated `loom_search` (replaces F05 stub)

```python
@server.tool()
async def loom_search(query: str, project: str | None = None, limit: int = 5) -> str:
    results = await hybrid_search(query, config, db, vault_client, project, limit)
    return build_context(results)
```

---

## Updated `loom_context` (SessionStart enrichment)

```python
@server.tool()
async def loom_context(repo_path: str) -> str:
    project = detect_project(repo_path)

    # 1. Load architecture.md directly
    architecture = await vault_client.read_note(f"projects/{project}/architecture.md")

    # 2. Hybrid search for recent relevant context
    recent = await hybrid_search(
        query=f"recent work on {project}",
        project=project,
        limit=3,
    )

    # 3. Load last 3 hot sessions directly
    hot_sessions = await get_recent_sessions(project, vault_client, count=3)

    return build_session_context(project, architecture, recent, hot_sessions)
```

---

## Acceptance Criteria

- [ ] `loom_search "auth decisions"` returns both vector matches AND graph-expanded neighbors
- [ ] Graph-expanded results have `graph_hops > 0` and lower combined score than direct vector hits
- [ ] Results ranked correctly: high vector score > graph neighbor > low vector score
- [ ] Duplicate paths removed (keep highest score)
- [ ] `build_context` respects ~4000 token budget
- [ ] `loom_context` at `SessionStart` returns architecture + recent sessions + hybrid search results
- [ ] `loom_search` with `project=None` searches across entire vault (not just one project)
- [ ] Empty vault returns empty results gracefully (no exception)

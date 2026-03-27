# F05: Vector Indexing — Pinecone + Ollama

**Status:** pending
**Depends on:** F01 (config), F02 (vault access + markdown parser)
**Review gate:** `loom reindex` completes, Pinecone index has vectors, `loom_search` returns semantically relevant results

---

## Goal

Build the indexing pipeline: scan `~/.loom/vault/`, chunk notes, generate embeddings via Ollama, and upsert into Pinecone. Keep the index in sync with vault changes via content hashing (only re-index changed files). After this feature, `loom_search` upgrades from keyword-only to semantic vector search.

---

## Files

```
loom/
  retrieval/
    embedder.py      ← Ollama embedding API client
    chunker.py       ← split notes into overlapping chunks
    pinecone_store.py← Pinecone upsert + query
    indexer.py       ← orchestrates scan → chunk → embed → upsert
    __init__.py
```

---

## Chunking Strategy (`chunker.py`)

Notes are split into overlapping chunks before embedding:

```python
@dataclass
class Chunk:
    chunk_id: str      # "{note_path}#{chunk_index}"
    note_path: str
    text: str
    metadata: dict     # project, type, tier, tags, date

def chunk_note(parsed: ParsedNote, chunk_size: int = 512, overlap: int = 64) -> list[Chunk]:
    """
    Split note body into chunks of ~chunk_size tokens with overlap.
    Each chunk inherits the note's frontmatter metadata.
    Heading boundaries respected (prefer splitting at ## headings).
    """
```

**Pinecone vector metadata per chunk:**
```json
{
  "note_path": "projects/my-repo/decisions/auth-jwt.md",
  "chunk_index": 0,
  "project": "my-repo",
  "type": "decision",
  "tier": "hot",
  "tags": ["auth", "jwt"],
  "date": "2026-03-26"
}
```

---

## `embedder.py` — Ollama Embedding Client

```python
class OllamaEmbedder:
    def __init__(self, base_url: str, model: str):
        self.client = httpx.AsyncClient(base_url=base_url)
        self.model = model

    async def embed(self, text: str) -> list[float]:
        """Single embedding. Raises OllamaNotAvailableError if Ollama is not running."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding with retry on rate limit."""
```

**Hard dependency:** raises `OllamaNotAvailableError` with install link if Ollama is unreachable.

---

## `pinecone_store.py` — Pinecone Client

```python
class PineconeStore:
    def __init__(self, api_key: str, index_name: str, dimensions: int):
        self.index = Pinecone(api_key=api_key).Index(index_name)

    async def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Upsert vectors with metadata. Batches of 100."""

    async def query(
        self,
        embedding: list[float],
        top_k: int = 10,
        filter: dict | None = None,   # e.g. {"project": "my-repo"}
    ) -> list[SearchResult]:
        """Cosine similarity query. Returns ranked SearchResult list."""

    async def delete_by_path(self, note_path: str) -> None:
        """Remove all vectors for a note (when note is deleted from vault)."""
```

---

## `indexer.py` — Full Indexing Pipeline

```python
async def reindex_vault(config: LoomConfig, db: Connection, force: bool = False) -> IndexReport:
    """
    Scans vault, finds changed files (via content hash in sync_state),
    chunks + embeds + upserts changed notes.
    Deletes Pinecone vectors for deleted notes.
    Returns IndexReport with counts.
    """

async def index_note(note_path: str, config: LoomConfig, db: Connection) -> None:
    """Index a single note. Called by capture engine after writing a new note."""
```

**Incremental sync flow:**
```
for each .md file in ~/.loom/vault/:
    hash = sha256(file content)
    if hash == sync_state[path]:
        skip
    else:
        parse → chunk → embed → upsert to Pinecone
        update sync_state[path] = hash

for each path in sync_state not in vault:
    delete from Pinecone
    delete from sync_state
```

---

## `loom reindex` CLI Command

```bash
$ loom reindex
Scanning vault... 47 notes found
  12 new, 3 changed, 32 unchanged
Embedding 15 notes (127 chunks)...
  ████████████████ 100% [127/127 chunks]
Upserted to Pinecone: 127 vectors
Deleted 0 stale vectors
Done in 8.3s

$ loom reindex --force   # re-index everything regardless of hash
```

---

## Integration with `loom_search` (upgrade from F03 stub)

After F05, `loom_search` uses vector search instead of keyword search:

```python
async def loom_search(query: str, project: str | None, limit: int = 5) -> list[dict]:
    embedding = await embedder.embed(query)
    filter = {"project": project} if project else None
    results = await pinecone_store.query(embedding, top_k=limit * 2, filter=filter)
    # graph expansion added in F07
    return results[:limit]
```

---

## New CLI Commands After F05

| Command | Description |
|---------|-------------|
| `loom reindex` | Incrementally re-index changed vault notes |
| `loom reindex --force` | Re-index all notes |
| `loom reindex --path <file>` | Re-index a single note |

---

## Acceptance Criteria

- [ ] `loom reindex` scans vault, embeds all notes, upserts to Pinecone
- [ ] Only changed files (by content hash) are re-indexed on subsequent runs
- [ ] Deleted notes are removed from Pinecone
- [ ] `loom_search "auth decisions"` returns semantically relevant notes (not just keyword matches)
- [ ] `loom_search` results filtered by `project` metadata correctly
- [ ] `OllamaNotAvailableError` raised with helpful message if Ollama is not running
- [ ] New notes written by capture engine (F04) are auto-indexed immediately after write
- [ ] `loom reindex --force` re-embeds all notes regardless of hash

"""Indexing pipeline — scan vault, chunk, embed, upsert to ChromaDB."""

import hashlib
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

from loom.config import LoomConfig
from loom.db import get_connection
from loom.retrieval.chroma_store import ChromaStore
from loom.retrieval.chunker import Chunk, chunk_note
from loom.retrieval.embedder import OllamaEmbedder
from loom.vault.markdown import parse_note


@dataclass
class IndexReport:
    """Summary of an indexing run."""

    total_notes: int = 0
    new_notes: int = 0
    changed_notes: int = 0
    unchanged_notes: int = 0
    deleted_notes: int = 0
    total_chunks: int = 0
    vectors_upserted: int = 0
    chunks_skipped: int = 0


async def reindex_vault(
    config: LoomConfig,
    force: bool = False,
    single_path: str | None = None,
) -> IndexReport:
    """Scan the vault and index changed notes into ChromaDB.

    Incremental at two levels:
    - Note level: skip notes whose content hash is unchanged.
    - Chunk level: within a changed note, only re-embed chunks whose
      text has changed (content-addressed IDs ensure stable tracking).

    Use ``force=True`` to re-embed all chunks regardless of stored hashes.

    Args:
        config: Loom configuration.
        force: If True, re-index all chunks of all notes.
        single_path: If set, only index this single vault-relative path.

    Returns:
        IndexReport with counts of what was processed.
    """
    report = IndexReport()
    vault_path = Path(config.vault_path)
    db = get_connection()

    embedder = OllamaEmbedder(
        base_url=config.ollama_base_url,
        model=config.embedding_model,
    )
    store = ChromaStore(persist_path=config.chroma_path)

    try:
        if single_path:
            abs_path = vault_path / single_path
            if abs_path.exists():
                await _index_file(
                    abs_path, vault_path, db, embedder, store, report, force, config,
                )
            return report

        vault_files = _scan_vault(vault_path)
        report.total_notes = len(vault_files)

        for abs_path, _rel_path in vault_files:
            await _index_file(
                abs_path, vault_path, db, embedder, store, report, force, config,
            )

        if not single_path:
            current_paths = {rel for _, rel in vault_files}
            report.deleted_notes = await _cleanup_stale(db, store, current_paths)

    finally:
        await embedder.close()
        db.close()

    return report


async def index_note(
    note_path: str,
    config: LoomConfig,
) -> None:
    """Index a single note immediately after writing it to the vault.

    Called by the capture engine after creating a new session or
    decision note.

    Args:
        note_path: Vault-relative path of the note.
        config: Loom configuration.
    """
    await reindex_vault(config, force=True, single_path=note_path)


def _scan_vault(vault_path: Path) -> list[tuple[Path, str]]:
    """Find all .md files in the vault.

    Returns:
        List of (absolute_path, vault_relative_path) tuples, sorted by path.
    """
    results: list[tuple[Path, str]] = []
    for md_file in vault_path.rglob("*.md"):
        rel = str(md_file.relative_to(vault_path))
        results.append((md_file, rel))
    return sorted(results, key=lambda x: x[1])


def _content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_stored_hash(db: sqlite3.Connection, path: str) -> str | None:
    """Look up the stored content hash for a note path."""
    cursor = db.execute(
        "SELECT content_hash FROM sync_state WHERE path = ?",
        (path,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _update_hash(db: sqlite3.Connection, path: str, hash_val: str) -> None:
    """Insert or update the content hash for a note path."""
    db.execute(
        """INSERT INTO sync_state (path, content_hash, indexed_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(path) DO UPDATE SET
             content_hash = excluded.content_hash,
             indexed_at = excluded.indexed_at""",
        (path, hash_val),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Chunk-level state helpers
# ---------------------------------------------------------------------------


def _get_chunk_hashes(db: sqlite3.Connection, note_path: str) -> dict[str, str]:
    """Return {chunk_id: chunk_hash} for all stored chunks of a note."""
    cursor = db.execute(
        "SELECT chunk_id, chunk_hash FROM chunk_state WHERE note_path = ?",
        (note_path,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def _upsert_chunk_state(
    db: sqlite3.Connection,
    chunk_id: str,
    note_path: str,
    chunk_hash: str,
) -> None:
    db.execute(
        """INSERT INTO chunk_state (chunk_id, note_path, chunk_hash, indexed_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(chunk_id) DO UPDATE SET
             chunk_hash = excluded.chunk_hash,
             indexed_at = excluded.indexed_at""",
        (chunk_id, note_path, chunk_hash),
    )


def _delete_chunk_states(db: sqlite3.Connection, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    placeholders = ",".join("?" * len(chunk_ids))
    db.execute(f"DELETE FROM chunk_state WHERE chunk_id IN ({placeholders})", chunk_ids)


# ---------------------------------------------------------------------------
# Note-level embedding helpers
# ---------------------------------------------------------------------------


def _pack_embedding(vector: list[float]) -> bytes:
    """Serialize a float list to a compact binary blob (IEEE 754 doubles)."""
    return struct.pack(f"{len(vector)}d", *vector)


def _unpack_embedding(blob: bytes) -> list[float]:
    """Deserialize a binary blob back to a float list."""
    n = len(blob) // 8
    return list(struct.unpack(f"{n}d", blob))


def _mean_pool(embeddings: list[list[float]]) -> list[float]:
    """Compute element-wise mean of a list of equal-length vectors."""
    if not embeddings:
        return []
    dim = len(embeddings[0])
    totals = [0.0] * dim
    for vec in embeddings:
        for i, v in enumerate(vec):
            totals[i] += v
    n = len(embeddings)
    return [t / n for t in totals]


def _upsert_note_embedding(
    db: sqlite3.Connection, note_path: str, vector: list[float]
) -> None:
    blob = _pack_embedding(vector)
    db.execute(
        """INSERT INTO note_embeddings (note_path, embedding, indexed_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(note_path) DO UPDATE SET
             embedding = excluded.embedding,
             indexed_at = excluded.indexed_at""",
        (note_path, blob),
    )


# ---------------------------------------------------------------------------
# Core indexing logic
# ---------------------------------------------------------------------------


async def _index_file(
    abs_path: Path,
    vault_path: Path,
    db: sqlite3.Connection,
    embedder: OllamaEmbedder,
    store: ChromaStore,
    report: IndexReport,
    force: bool,
    config: LoomConfig,
) -> None:
    """Index a single file with chunk-level incremental tracking.

    Flow:
    1. Note-level hash check — skip unchanged notes (unless force=True).
    2. Async semantic chunking (uses embedder for breakpoint detection).
    3. Chunk-level hash check — only re-embed chunks whose text changed.
    4. Delete removed chunks from ChromaDB and chunk_state.
    5. Embed and upsert new/changed chunks.
    6. Store mean-pooled note embedding for link discovery.
    7. Update note-level hash in sync_state.
    """
    rel_path = str(abs_path.relative_to(vault_path))
    content = abs_path.read_text(encoding="utf-8")
    current_hash = _content_hash(content)

    stored_hash = _get_stored_hash(db, rel_path)

    if not force and stored_hash == current_hash:
        report.unchanged_notes += 1
        return

    if stored_hash is None:
        report.new_notes += 1
    else:
        report.changed_notes += 1

    parsed = parse_note(rel_path, content)
    new_chunks: list[Chunk] = await chunk_note(
        parsed,
        embedder=embedder,
        semantic_threshold=config.semantic_chunking_threshold,
    )

    if not new_chunks:
        _update_hash(db, rel_path, current_hash)
        return

    # Compute per-chunk hash (hash of text only, not metadata)
    new_chunk_hashes = {c.chunk_id: _content_hash(c.text) for c in new_chunks}
    stored_chunk_hashes = _get_chunk_hashes(db, rel_path)

    # Determine which chunk IDs were removed (present before, absent now)
    removed_ids = [cid for cid in stored_chunk_hashes if cid not in new_chunk_hashes]
    if removed_ids:
        await store.delete_ids(removed_ids)
        _delete_chunk_states(db, removed_ids)

    # Partition new chunks into changed vs. unchanged
    chunks_to_embed: list[Chunk] = []
    for chunk in new_chunks:
        if force or new_chunk_hashes[chunk.chunk_id] != stored_chunk_hashes.get(chunk.chunk_id):
            chunks_to_embed.append(chunk)
        else:
            report.chunks_skipped += 1

    report.total_chunks += len(new_chunks)

    if chunks_to_embed:
        texts = [c.text for c in chunks_to_embed]
        new_embeddings = await embedder.embed_batch(texts)
        upserted = await store.upsert_chunks(chunks_to_embed, new_embeddings)
        report.vectors_upserted += upserted

        for chunk, emb_hash in zip(
            chunks_to_embed,
            [new_chunk_hashes[c.chunk_id] for c in chunks_to_embed],
            strict=True,
        ):
            _upsert_chunk_state(db, chunk.chunk_id, rel_path, emb_hash)

    # Store note-level mean-pooled embedding for semantic link discovery.
    # We need embeddings for ALL chunks of this note (not just the changed ones).
    # Fetch existing vectors for unchanged chunks from ChromaDB by querying them,
    # then combine with the freshly-computed vectors.
    if chunks_to_embed:
        all_embeddings = await _get_all_chunk_embeddings(
            store, new_chunks, chunks_to_embed, new_embeddings,
        )
        if all_embeddings:
            note_vec = _mean_pool(all_embeddings)
            _upsert_note_embedding(db, rel_path, note_vec)

    db.commit()
    _update_hash(db, rel_path, current_hash)


async def _get_all_chunk_embeddings(
    store: ChromaStore,
    all_chunks: list[Chunk],
    freshly_embedded: list[Chunk],
    fresh_vectors: list[list[float]],
) -> list[list[float]]:
    """Collect embeddings for all chunks of a note.

    For chunks that were just re-embedded, use the fresh vectors directly.
    For unchanged chunks, re-embed their stored text via the store query —
    ChromaDB does not expose a direct "get by id with embedding" API, so we
    re-embed only the unchanged chunks by fetching them from the collection.

    In practice, if most chunks are unchanged this is a no-op because we
    already computed their embeddings during the unchanged-check pass.
    Since ChromaDB's collection.get() does return embeddings when asked, we
    use that path for efficiency.
    """
    fresh_map: dict[str, list[float]] = {
        c.chunk_id: vec for c, vec in zip(freshly_embedded, fresh_vectors, strict=True)
    }

    results: list[list[float]] = []
    stale_chunks = [c for c in all_chunks if c.chunk_id not in fresh_map]

    if stale_chunks:
        stale_ids = [c.chunk_id for c in stale_chunks]
        try:
            fetched = store.get_embeddings_by_ids(stale_ids)
            stale_map = dict(zip(stale_ids, fetched, strict=False))
        except Exception:
            stale_map = {}
    else:
        stale_map = {}

    for chunk in all_chunks:
        if chunk.chunk_id in fresh_map:
            results.append(fresh_map[chunk.chunk_id])
        elif chunk.chunk_id in stale_map:
            results.append(stale_map[chunk.chunk_id])

    return results


async def _cleanup_stale(
    db: sqlite3.Connection,
    store: ChromaStore,
    current_paths: set[str],
) -> int:
    """Remove sync_state, chunk_state, note_embeddings, and ChromaDB vectors
    for notes that no longer exist in the vault."""
    cursor = db.execute("SELECT path FROM sync_state")
    stored_paths = {row[0] for row in cursor.fetchall()}

    stale = stored_paths - current_paths
    for path in stale:
        await store.delete_by_path(path)
        db.execute("DELETE FROM sync_state WHERE path = ?", (path,))
        db.execute("DELETE FROM chunk_state WHERE note_path = ?", (path,))
        db.execute("DELETE FROM note_embeddings WHERE note_path = ?", (path,))

    if stale:
        db.commit()

    return len(stale)

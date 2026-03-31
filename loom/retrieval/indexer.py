"""Indexing pipeline — scan vault, chunk, embed, upsert to ChromaDB."""

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from loom.config import LoomConfig
from loom.db import get_connection
from loom.retrieval.chunker import chunk_note
from loom.retrieval.chroma_store import ChromaStore
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


async def reindex_vault(
    config: LoomConfig,
    force: bool = False,
    single_path: str | None = None,
) -> IndexReport:
    """Scan the vault and index changed notes into ChromaDB.

    Incremental by default: only re-indexes notes whose content hash
    has changed since the last run. Use force=True to re-index everything.

    Args:
        config: Loom configuration.
        force: If True, re-index all notes regardless of hash.
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
                    abs_path, vault_path, db, embedder, store, report, force,
                )
            return report

        vault_files = _scan_vault(vault_path)
        report.total_notes = len(vault_files)

        for abs_path, rel_path in vault_files:
            await _index_file(
                abs_path, vault_path, db, embedder, store, report, force,
            )

        if not single_path:
            current_paths = {rel for _, rel in vault_files}
            report.deleted_notes = await _cleanup_stale(
                db, store, current_paths,
            )

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
        List of (absolute_path, vault_relative_path) tuples.
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


async def _index_file(
    abs_path: Path,
    vault_path: Path,
    db: sqlite3.Connection,
    embedder: OllamaEmbedder,
    store: ChromaStore,
    report: IndexReport,
    force: bool,
) -> None:
    """Index a single file: hash check -> parse -> chunk -> embed -> upsert."""
    rel_path = str(abs_path.relative_to(vault_path))
    content = abs_path.read_text(encoding="utf-8")
    current_hash = _content_hash(content)

    if not force:
        stored_hash = _get_stored_hash(db, rel_path)
        if stored_hash == current_hash:
            report.unchanged_notes += 1
            return
        if stored_hash is None:
            report.new_notes += 1
        else:
            report.changed_notes += 1
    else:
        stored_hash = _get_stored_hash(db, rel_path)
        if stored_hash is None:
            report.new_notes += 1
        else:
            report.changed_notes += 1

    parsed = parse_note(rel_path, content)
    chunks = chunk_note(parsed)

    if not chunks:
        _update_hash(db, rel_path, current_hash)
        return

    texts = [c.text for c in chunks]
    embeddings = await embedder.embed_batch(texts)

    await store.delete_by_path(rel_path)

    upserted = await store.upsert_chunks(chunks, embeddings)
    report.total_chunks += len(chunks)
    report.vectors_upserted += upserted

    _update_hash(db, rel_path, current_hash)


async def _cleanup_stale(
    db: sqlite3.Connection,
    store: ChromaStore,
    current_paths: set[str],
) -> int:
    """Remove sync_state entries and ChromaDB vectors for deleted notes."""
    cursor = db.execute("SELECT path FROM sync_state")
    stored_paths = {row[0] for row in cursor.fetchall()}

    stale = stored_paths - current_paths
    for path in stale:
        await store.delete_by_path(path)
        db.execute("DELETE FROM sync_state WHERE path = ?", (path,))

    if stale:
        db.commit()

    return len(stale)

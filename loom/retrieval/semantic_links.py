"""Semantic link discovery — find related notes via embedding similarity.

Uses the mean-pooled note embeddings stored in ``note_embeddings`` (SQLite)
to compute pairwise cosine similarity across all indexed notes.  Pairs that
exceed the configured threshold are inserted into ``pending_links`` for user
review via ``loom review-links``.
"""

from __future__ import annotations

import math
import sqlite3
import struct
from dataclasses import dataclass


@dataclass
class LinkCandidate:
    """A discovered semantic relationship between two vault notes."""

    source_path: str
    target_path: str
    similarity: float
    source_excerpt: str
    target_excerpt: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_links(
    db: sqlite3.Connection,
    threshold: float = 0.82,
    max_per_note: int = 5,
) -> int:
    """Scan all note embeddings and queue semantically similar pairs.

    Computes pairwise cosine similarity across all notes stored in
    ``note_embeddings``.  For each note, takes the top ``max_per_note``
    neighbours above ``threshold``, filters out pairs that already exist as
    wikilinks in ``graph_cache`` or are already recorded in ``pending_links``,
    and inserts the remainder as pending suggestions.

    This function is synchronous because it operates entirely on SQLite data
    and in-process numpy-free math — no async I/O required.

    Args:
        db: Open SQLite connection with the Loom schema.
        threshold: Cosine similarity floor for link candidacy.
        max_per_note: Maximum new candidates to queue per source note.

    Returns:
        Number of new candidates inserted into ``pending_links``.
    """
    note_data = _load_note_embeddings(db)
    if len(note_data) < 2:
        return 0

    paths = [nd[0] for nd in note_data]
    vectors = [nd[1] for nd in note_data]
    excerpts = {nd[0]: nd[2] for nd in note_data}

    # Normalise all vectors for cosine similarity via dot product.
    normed = [_normalise(v) for v in vectors]

    existing_links = _load_existing_links(db)
    candidates: list[LinkCandidate] = []

    for i, source_path in enumerate(paths):
        scores: list[tuple[float, str]] = []

        for j, target_path in enumerate(paths):
            if i == j:
                continue
            pair = (source_path, target_path)
            pair_rev = (target_path, source_path)
            if pair in existing_links or pair_rev in existing_links:
                continue
            sim = _dot(normed[i], normed[j])
            if sim >= threshold:
                scores.append((sim, target_path))

        scores.sort(key=lambda x: x[0], reverse=True)

        for sim, target_path in scores[:max_per_note]:
            candidates.append(
                LinkCandidate(
                    source_path=source_path,
                    target_path=target_path,
                    similarity=sim,
                    source_excerpt=excerpts.get(source_path, "")[:300],
                    target_excerpt=excerpts.get(target_path, "")[:300],
                )
            )

    return _insert_candidates(db, candidates)


def queue_search_links(
    db: sqlite3.Connection,
    source_path: str,
    result_paths: list[str],
    similarities: list[float],
    threshold: float = 0.82,
) -> int:
    """Queue link candidates discovered during a hybrid search.

    Called by the retrieval engine after Stage 3 reranking when
    ``semantic_links.auto_on_search`` is enabled.  Only queues pairs whose
    similarity exceeds the threshold and that are not already linked.

    Args:
        db: Open SQLite connection.
        source_path: The note the user searched from (context note).
        result_paths: Paths of the top-ranked retrieval results.
        similarities: Corresponding similarity scores (same order).
        threshold: Minimum similarity to queue a pair.

    Returns:
        Number of new candidates inserted.
    """
    if not source_path or not result_paths:
        return 0

    existing_links = _load_existing_links(db)
    candidates: list[LinkCandidate] = []

    for target_path, sim in zip(result_paths, similarities, strict=False):
        if target_path == source_path:
            continue
        pair = (source_path, target_path)
        pair_rev = (target_path, source_path)
        if pair in existing_links or pair_rev in existing_links:
            continue
        if sim >= threshold:
            candidates.append(
                LinkCandidate(
                    source_path=source_path,
                    target_path=target_path,
                    similarity=sim,
                    source_excerpt="",
                    target_excerpt="",
                )
            )

    return _insert_candidates(db, candidates)


def get_pending_links(
    db: sqlite3.Connection,
    limit: int = 50,
) -> list[dict]:
    """Return pending link suggestions as plain dicts for the review UI.

    Args:
        db: Open SQLite connection.
        limit: Maximum number of rows to return.

    Returns:
        List of dicts with keys: id, source_path, target_path, similarity,
        source_excerpt, target_excerpt, created_at.
    """
    cursor = db.execute(
        """SELECT id, source_path, target_path, similarity,
                  source_excerpt, target_excerpt, created_at
           FROM pending_links
           WHERE status = 'pending'
           ORDER BY similarity DESC
           LIMIT ?""",
        (limit,),
    )
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row, strict=True)) for row in cursor.fetchall()]


def approve_link(db: sqlite3.Connection, link_id: int) -> tuple[str, str] | None:
    """Mark a pending link as approved and add it to graph_cache.

    Returns the (source_path, target_path) pair so the caller can write the
    Obsidian wikilink, or None if the link was not found.
    """
    cursor = db.execute(
        "SELECT source_path, target_path FROM pending_links WHERE id = ? AND status = 'pending'",
        (link_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    source_path, target_path = row[0], row[1]

    db.execute(
        "UPDATE pending_links SET status = 'approved' WHERE id = ?",
        (link_id,),
    )
    db.execute(
        """INSERT OR IGNORE INTO graph_cache (from_path, to_path)
           VALUES (?, ?)""",
        (source_path, target_path),
    )
    db.commit()
    return source_path, target_path


def reject_link(db: sqlite3.Connection, link_id: int) -> bool:
    """Mark a pending link as rejected.

    Returns True if the link was found and updated, False otherwise.
    """
    cursor = db.execute(
        "UPDATE pending_links SET status = 'rejected' WHERE id = ? AND status = 'pending'",
        (link_id,),
    )
    db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_note_embeddings(db: sqlite3.Connection) -> list[tuple[str, list[float], str]]:
    """Load all stored note embeddings.

    Returns a list of (note_path, vector, excerpt) tuples.
    The excerpt is derived from the sync_state table — we don't store the
    full note text in SQLite, so the excerpt is just the note path for now.
    (The UI reads actual excerpts from ChromaDB or the vault at review time.)
    """
    cursor = db.execute("SELECT note_path, embedding FROM note_embeddings")
    result: list[tuple[str, list[float], str]] = []
    for note_path, blob in cursor.fetchall():
        if not blob:
            continue
        try:
            vector = _unpack_embedding(blob)
        except struct.error:
            continue
        result.append((note_path, vector, note_path))
    return result


def _load_existing_links(db: sqlite3.Connection) -> set[tuple[str, str]]:
    """Load all existing wikilinks and already-recorded pending_links pairs."""
    links: set[tuple[str, str]] = set()

    for row in db.execute("SELECT from_path, to_path FROM graph_cache").fetchall():
        links.add((row[0], row[1]))

    for row in db.execute(
        "SELECT source_path, target_path FROM pending_links WHERE status != 'rejected'"
    ).fetchall():
        links.add((row[0], row[1]))

    return links


def _insert_candidates(db: sqlite3.Connection, candidates: list[LinkCandidate]) -> int:
    """Insert link candidates into pending_links, ignoring duplicates."""
    inserted = 0
    for c in candidates:
        try:
            db.execute(
                """INSERT OR IGNORE INTO pending_links
                   (source_path, target_path, similarity, source_excerpt, target_excerpt)
                   VALUES (?, ?, ?, ?, ?)""",
                (c.source_path, c.target_path, c.similarity,
                 c.source_excerpt, c.target_excerpt),
            )
            inserted += db.execute("SELECT changes()").fetchone()[0]
        except sqlite3.IntegrityError:
            continue

    db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Vector math (stdlib-only, no numpy dependency)
# ---------------------------------------------------------------------------


def _normalise(v: list[float]) -> list[float]:
    """Return L2-normalised copy of a vector."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return v[:]
    return [x / norm for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    """Dot product of two equal-length vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def _unpack_embedding(blob: bytes) -> list[float]:
    """Deserialise a binary blob (IEEE 754 doubles) to a float list."""
    n = len(blob) // 8
    return list(struct.unpack(f"{n}d", blob))

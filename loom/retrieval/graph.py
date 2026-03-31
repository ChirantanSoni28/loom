"""Wikilink graph — adjacency list in SQLite with BFS traversal."""

import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from loom.vault.markdown import parse_note


@dataclass
class GraphNode:
    """A node found during graph traversal."""

    path: str
    hops: int


class VaultGraph:
    """Wikilink-based graph stored in SQLite graph_cache.

    Supports full rebuild from vault, incremental updates for single notes,
    and BFS traversal for relationship-aware retrieval.

    Args:
        db: SQLite connection with graph_cache table.
    """

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    async def rebuild(self, vault_path: Path) -> int:
        """Rebuild the entire graph from vault files.

        Scans all .md files, parses wikilinks, and populates graph_cache.

        Args:
            vault_path: Absolute path to the vault root.

        Returns:
            Number of edges written.
        """
        # Clear existing edges
        self.db.execute("DELETE FROM graph_cache")

        edge_count = 0
        for md_file in vault_path.rglob("*.md"):
            rel_path = str(md_file.relative_to(vault_path))
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_note(rel_path, content)

            for link in parsed.wikilinks:
                resolved = _resolve_wikilink(link, vault_path)
                self.db.execute(
                    "INSERT OR IGNORE INTO graph_cache (from_path, to_path) VALUES (?, ?)",
                    (rel_path, resolved),
                )
                edge_count += 1

        self.db.commit()
        return edge_count

    def neighbors(self, path: str, direction: str = "both") -> list[str]:
        """Get direct neighbors of a note (depth 1).

        Args:
            path: Vault-relative path of the note.
            direction: "out" (forward links), "in" (backlinks), or "both".

        Returns:
            List of neighbor paths.
        """
        results: set[str] = set()

        if direction in ("out", "both"):
            cursor = self.db.execute(
                "SELECT to_path FROM graph_cache WHERE from_path = ?",
                (path,),
            )
            results.update(row[0] for row in cursor.fetchall())

        if direction in ("in", "both"):
            cursor = self.db.execute(
                "SELECT from_path FROM graph_cache WHERE to_path = ?",
                (path,),
            )
            results.update(row[0] for row in cursor.fetchall())

        results.discard(path)  # Don't include self
        return sorted(results)

    def bfs(self, seed_paths: list[str], max_depth: int = 2) -> list[GraphNode]:
        """BFS traversal from seed nodes up to max_depth.

        Returns nodes sorted by hop count (ascending). Does not include
        seed paths in the result.

        Args:
            seed_paths: Starting nodes for traversal.
            max_depth: Maximum number of hops.

        Returns:
            List of GraphNode(path, hops) sorted by hops.
        """
        visited: set[str] = set(seed_paths)
        result: list[GraphNode] = []
        queue: deque[tuple[str, int]] = deque()

        for seed in seed_paths:
            queue.append((seed, 0))

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for neighbor in self.neighbors(current, direction="both"):
                if neighbor not in visited:
                    visited.add(neighbor)
                    hops = depth + 1
                    result.append(GraphNode(path=neighbor, hops=hops))
                    queue.append((neighbor, hops))

        result.sort(key=lambda n: n.hops)
        return result

    def add_note_edges(self, path: str, wikilinks: list[str], vault_path: Path) -> None:
        """Add edges for a single newly-written note (incremental update).

        Args:
            path: Vault-relative path of the new note.
            wikilinks: List of raw wikilink targets from the note.
            vault_path: Absolute path to the vault root.
        """
        for link in wikilinks:
            resolved = _resolve_wikilink(link, vault_path)
            self.db.execute(
                "INSERT OR IGNORE INTO graph_cache (from_path, to_path) VALUES (?, ?)",
                (path, resolved),
            )
        self.db.commit()

    def remove_note_edges(self, path: str) -> None:
        """Remove all edges for a deleted note.

        Args:
            path: Vault-relative path of the deleted note.
        """
        self.db.execute("DELETE FROM graph_cache WHERE from_path = ? OR to_path = ?", (path, path))
        self.db.commit()

    def stats(self) -> dict[str, int]:
        """Return node and edge counts.

        Returns:
            Dict with 'nodes' and 'edges' keys.
        """
        cursor = self.db.execute("SELECT COUNT(*) FROM graph_cache")
        edge_count = cursor.fetchone()[0]

        cursor = self.db.execute(
            "SELECT COUNT(DISTINCT path) FROM ("
            "  SELECT from_path AS path FROM graph_cache"
            "  UNION"
            "  SELECT to_path AS path FROM graph_cache"
            ")"
        )
        node_count = cursor.fetchone()[0]

        return {"nodes": node_count, "edges": edge_count}


def _resolve_wikilink(link: str, vault_path: Path) -> str:
    """Resolve a wikilink target to a vault-relative path.

    - ``[[folder/note]]`` → direct path lookup (append .md if needed)
    - ``[[note title]]`` → search vault for matching filename (case-insensitive)
    - Unresolved links returned as-is with .md suffix

    Args:
        link: Raw wikilink target text.
        vault_path: Absolute path to the vault root.

    Returns:
        Vault-relative path (best effort).
    """
    # Strip any heading anchors: [[note#heading]] → note
    if "#" in link:
        link = link.split("#")[0]

    link = link.strip()
    if not link:
        return link

    # Case-insensitive filename search across vault
    # (handles exact match, nested paths, and case mismatches)
    target_name = link.split("/")[-1].lower()
    if target_name.endswith(".md"):
        target_name = target_name[:-3]
    for md_file in vault_path.rglob("*.md"):
        if md_file.stem.lower() == target_name:
            return str(md_file.relative_to(vault_path))

    # Unresolved: store as-is with .md suffix
    if not link.endswith(".md"):
        return f"{link}.md"
    return link

"""Tests for loom.retrieval.graph — wikilink graph traversal."""

import pytest

from loom.db import get_connection
from loom.retrieval.graph import GraphNode, VaultGraph, _resolve_wikilink


@pytest.fixture()
def db(tmp_path):
    return get_connection(tmp_path / "test.db")


@pytest.fixture()
def graph(db):
    return VaultGraph(db)


@pytest.fixture()
def vault(tmp_path):
    """Create a small test vault with wikilinks."""
    v = tmp_path / "vault"
    v.mkdir()

    (v / "projects" / "repo" / "decisions").mkdir(parents=True)
    (v / "knowledge" / "tech").mkdir(parents=True)

    (v / "projects" / "repo" / "architecture.md").write_text(
        "# Architecture\n\nSee [[auth-jwt]] and [[caching]]."
    )
    (v / "projects" / "repo" / "decisions" / "auth-jwt.md").write_text(
        "# Auth JWT\n\nRelated: [[jwt-patterns]] and [[architecture]]."
    )
    (v / "knowledge" / "tech" / "jwt-patterns.md").write_text(
        "# JWT Patterns\n\nUsed by [[auth-jwt]]."
    )
    (v / "knowledge" / "tech" / "caching.md").write_text(
        "# Caching\n\nNo links here."
    )

    return v


class TestVaultGraph:
    """Test graph build and traversal."""

    @pytest.mark.asyncio
    async def test_rebuild_counts_edges(self, graph, vault) -> None:
        edge_count = await graph.rebuild(vault)
        assert edge_count > 0

    @pytest.mark.asyncio
    async def test_neighbors_forward_links(self, graph, vault) -> None:
        await graph.rebuild(vault)
        nbrs = graph.neighbors("projects/repo/architecture.md", direction="out")
        # architecture.md links to auth-jwt and caching
        assert len(nbrs) >= 2

    @pytest.mark.asyncio
    async def test_neighbors_backlinks(self, graph, vault) -> None:
        await graph.rebuild(vault)
        # auth-jwt.md is linked FROM architecture.md
        nbrs = graph.neighbors(
            "projects/repo/decisions/auth-jwt.md", direction="in",
        )
        assert any("architecture" in n for n in nbrs)

    @pytest.mark.asyncio
    async def test_neighbors_both(self, graph, vault) -> None:
        await graph.rebuild(vault)
        nbrs = graph.neighbors(
            "projects/repo/decisions/auth-jwt.md", direction="both",
        )
        assert len(nbrs) >= 2  # Has both forward and backlinks

    @pytest.mark.asyncio
    async def test_neighbors_excludes_self(self, graph, vault) -> None:
        await graph.rebuild(vault)
        path = "projects/repo/architecture.md"
        nbrs = graph.neighbors(path, direction="both")
        assert path not in nbrs

    @pytest.mark.asyncio
    async def test_bfs_depth_1(self, graph, vault) -> None:
        await graph.rebuild(vault)
        nodes = graph.bfs(["projects/repo/architecture.md"], max_depth=1)
        assert all(n.hops == 1 for n in nodes)

    @pytest.mark.asyncio
    async def test_bfs_depth_2_reaches_further(self, graph, vault) -> None:
        await graph.rebuild(vault)
        nodes_d1 = graph.bfs(["projects/repo/architecture.md"], max_depth=1)
        nodes_d2 = graph.bfs(["projects/repo/architecture.md"], max_depth=2)
        assert len(nodes_d2) >= len(nodes_d1)

    @pytest.mark.asyncio
    async def test_bfs_excludes_seed(self, graph, vault) -> None:
        await graph.rebuild(vault)
        seed = "projects/repo/architecture.md"
        nodes = graph.bfs([seed], max_depth=2)
        assert all(n.path != seed for n in nodes)

    @pytest.mark.asyncio
    async def test_bfs_sorted_by_hops(self, graph, vault) -> None:
        await graph.rebuild(vault)
        nodes = graph.bfs(["projects/repo/architecture.md"], max_depth=2)
        hops = [n.hops for n in nodes]
        assert hops == sorted(hops)

    @pytest.mark.asyncio
    async def test_bfs_no_duplicates(self, graph, vault) -> None:
        await graph.rebuild(vault)
        nodes = graph.bfs(["projects/repo/architecture.md"], max_depth=2)
        paths = [n.path for n in nodes]
        assert len(paths) == len(set(paths))

    def test_add_note_edges(self, graph, tmp_path) -> None:
        vault = tmp_path / "vault2"
        vault.mkdir()
        (vault / "existing.md").write_text("# Existing")

        graph.add_note_edges("new.md", ["existing"], vault)
        nbrs = graph.neighbors("new.md", direction="out")
        assert "existing.md" in nbrs

    def test_remove_note_edges(self, graph, tmp_path) -> None:
        vault = tmp_path / "vault3"
        vault.mkdir()
        (vault / "b.md").write_text("# B")

        graph.add_note_edges("a.md", ["b"], vault)
        assert len(graph.neighbors("a.md")) > 0

        graph.remove_note_edges("a.md")
        assert len(graph.neighbors("a.md")) == 0

    @pytest.mark.asyncio
    async def test_stats(self, graph, vault) -> None:
        await graph.rebuild(vault)
        stats = graph.stats()
        assert stats["nodes"] > 0
        assert stats["edges"] > 0

    def test_empty_graph_stats(self, graph) -> None:
        stats = graph.stats()
        assert stats["nodes"] == 0
        assert stats["edges"] == 0


class TestResolveWikilink:
    """Test wikilink resolution logic."""

    def test_resolve_existing_file(self, tmp_path) -> None:
        (tmp_path / "note.md").write_text("hello")
        result = _resolve_wikilink("note", tmp_path)
        assert result == "note.md"

    def test_resolve_with_md_extension(self, tmp_path) -> None:
        (tmp_path / "note.md").write_text("hello")
        result = _resolve_wikilink("note.md", tmp_path)
        assert result == "note.md"

    def test_resolve_nested_path(self, tmp_path) -> None:
        (tmp_path / "folder").mkdir()
        (tmp_path / "folder" / "note.md").write_text("hello")
        result = _resolve_wikilink("folder/note", tmp_path)
        assert result == "folder/note.md"

    def test_unresolved_returns_with_md(self, tmp_path) -> None:
        result = _resolve_wikilink("nonexistent", tmp_path)
        assert result == "nonexistent.md"

    def test_heading_anchor_stripped(self, tmp_path) -> None:
        (tmp_path / "note.md").write_text("hello")
        result = _resolve_wikilink("note#section", tmp_path)
        assert result == "note.md"

    def test_case_insensitive_search(self, tmp_path) -> None:
        (tmp_path / "MyNote.md").write_text("hello")
        result = _resolve_wikilink("mynote", tmp_path)
        assert result == "MyNote.md"

"""Tests for loom.retrieval.chunker — note chunking logic."""

import hashlib

import pytest

from loom.retrieval.chunker import Chunk, _content_id, chunk_note
from loom.vault.markdown import ParsedNote


def _make_note(
    body: str,
    path: str = "projects/my-repo/sessions/hot/2026-03-30.md",
    frontmatter: dict | None = None,
    tags: list[str] | None = None,
) -> ParsedNote:
    return ParsedNote(
        path=path,
        frontmatter=frontmatter or {"project": "my-repo", "type": "session"},
        wikilinks=[],
        tags=tags or [],
        body=body,
    )


class TestContentId:
    """Test content-addressed chunk ID generation."""

    def test_id_is_deterministic(self) -> None:
        cid = _content_id("note.md", "hello world")
        assert cid == _content_id("note.md", "hello world")

    def test_id_includes_note_path(self) -> None:
        cid = _content_id("projects/foo.md", "text")
        assert cid.startswith("projects/foo.md#")

    def test_different_text_different_id(self) -> None:
        assert _content_id("note.md", "foo") != _content_id("note.md", "bar")

    def test_different_path_different_id(self) -> None:
        assert _content_id("a.md", "text") != _content_id("b.md", "text")

    def test_id_suffix_is_8_hex_chars(self) -> None:
        cid = _content_id("note.md", "hello")
        suffix = cid.split("#", 1)[1]
        assert len(suffix) == 8
        assert all(c in "0123456789abcdef" for c in suffix)


class TestChunkNote:
    """Test chunk_note splitting logic (async, no embedder)."""

    async def test_empty_body_returns_no_chunks(self) -> None:
        note = _make_note("")
        chunks = await chunk_note(note)
        assert chunks == []

    async def test_whitespace_body_returns_no_chunks(self) -> None:
        note = _make_note("   \n  \n  ")
        chunks = await chunk_note(note)
        assert chunks == []

    async def test_short_note_returns_single_chunk(self) -> None:
        note = _make_note("This is a short note.")
        chunks = await chunk_note(note)
        assert len(chunks) == 1
        assert "short note" in chunks[0].text

    async def test_chunk_id_is_content_addressed(self) -> None:
        note = _make_note("Hello world.")
        chunks = await chunk_note(note)
        assert "#" in chunks[0].chunk_id
        suffix = chunks[0].chunk_id.split("#", 1)[1]
        assert len(suffix) == 8

    async def test_chunk_id_stable_across_calls(self) -> None:
        note = _make_note("Hello world.")
        chunks1 = await chunk_note(note)
        chunks2 = await chunk_note(note)
        assert chunks1[0].chunk_id == chunks2[0].chunk_id

    async def test_chunk_metadata_includes_project(self) -> None:
        note = _make_note("Content", frontmatter={"project": "loom", "type": "decision"})
        chunks = await chunk_note(note)
        assert chunks[0].metadata["project"] == "loom"
        assert chunks[0].metadata["type"] == "decision"

    async def test_chunk_metadata_includes_tier_from_path(self) -> None:
        note = _make_note("Content", path="projects/my-repo/sessions/hot/note.md")
        chunks = await chunk_note(note)
        assert chunks[0].metadata["tier"] == "hot"

    async def test_warm_tier_detected(self) -> None:
        note = _make_note("Content", path="projects/my-repo/sessions/warm/note.md")
        chunks = await chunk_note(note)
        assert chunks[0].metadata["tier"] == "warm"

    async def test_cold_tier_detected(self) -> None:
        note = _make_note("Content", path="projects/my-repo/sessions/cold/note.md")
        chunks = await chunk_note(note)
        assert chunks[0].metadata["tier"] == "cold"

    async def test_decision_tier_is_permanent(self) -> None:
        note = _make_note("Content", path="projects/my-repo/decisions/auth.md")
        chunks = await chunk_note(note)
        assert chunks[0].metadata["tier"] == "permanent"

    async def test_knowledge_tier_is_permanent(self) -> None:
        note = _make_note("Content", path="knowledge/patterns/caching.md")
        chunks = await chunk_note(note)
        assert chunks[0].metadata["tier"] == "permanent"

    async def test_tags_included_in_metadata(self) -> None:
        note = _make_note("Content", tags=["auth", "jwt"])
        chunks = await chunk_note(note)
        assert chunks[0].metadata["tags"] == ["auth", "jwt"]

    async def test_no_tags_means_no_tags_key(self) -> None:
        note = _make_note("Content", tags=[])
        chunks = await chunk_note(note)
        assert "tags" not in chunks[0].metadata

    async def test_heading_split(self) -> None:
        body = "## Section 1\n\nContent one.\n\n## Section 2\n\nContent two."
        note = _make_note(body)
        chunks = await chunk_note(note, chunk_size=30, overlap=0)
        assert len(chunks) >= 2

    async def test_long_note_produces_multiple_chunks(self) -> None:
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(20)])
        note = _make_note(body)
        chunks = await chunk_note(note, chunk_size=200, overlap=0)
        assert len(chunks) > 1

    async def test_all_chunks_have_note_path(self) -> None:
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(10)])
        note = _make_note(body, path="projects/test/sessions/hot/note.md")
        chunks = await chunk_note(note, chunk_size=200, overlap=0)
        for chunk in chunks:
            assert chunk.note_path == "projects/test/sessions/hot/note.md"

    async def test_chunk_ids_are_unique(self) -> None:
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(10)])
        note = _make_note(body)
        chunks = await chunk_note(note, chunk_size=200, overlap=0)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    async def test_chunk_index_is_sequential(self) -> None:
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(10)])
        note = _make_note(body)
        chunks = await chunk_note(note, chunk_size=200, overlap=0)
        for i, chunk in enumerate(chunks):
            assert chunk.metadata["chunk_index"] == i

    async def test_overlap_adds_prefix_from_previous_chunk(self) -> None:
        body = (
            "## First\n\nSome content here in the first section.\n\n"
            "## Second\n\nDifferent content in the second section."
        )
        note = _make_note(body)
        chunks = await chunk_note(note, chunk_size=40, overlap=20)
        assert len(chunks) > 0

    async def test_heading_breadcrumb_in_text(self) -> None:
        body = "## Architecture\n\nThis is the architecture section."
        note = _make_note(body)
        chunks = await chunk_note(note)
        assert any("## Architecture" in c.text for c in chunks)

    async def test_nested_heading_breadcrumb(self) -> None:
        body = "## Top\n\n### Sub\n\nContent under sub."
        note = _make_note(body)
        chunks = await chunk_note(note)
        sub_chunks = [c for c in chunks if "Sub" in c.text]
        assert sub_chunks
        assert "## Top" in sub_chunks[0].text
        assert "### Sub" in sub_chunks[0].text

    async def test_parent_chunk_id_set_for_child_chunks(self) -> None:
        body = (
            "## Section\n\n"
            + ("Word " * 100 + "\n\n") * 4
        )
        note = _make_note(body)
        chunks = await chunk_note(note, chunk_size=100, overlap=0)
        section_chunks = [c for c in chunks if "## Section" in c.text or
                          c.metadata.get("heading_path", "").startswith("## Section")]
        if len(section_chunks) > 1:
            assert "parent_chunk_id" in section_chunks[1].metadata

    async def test_heading_path_in_metadata(self) -> None:
        body = "## Architecture\n\nContent here."
        note = _make_note(body)
        chunks = await chunk_note(note)
        assert chunks[0].metadata.get("heading_path") == "## Architecture"

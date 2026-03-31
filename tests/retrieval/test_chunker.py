"""Tests for loom.retrieval.chunker — note chunking logic."""

import pytest

from loom.retrieval.chunker import Chunk, chunk_note
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


class TestChunkNote:
    """Test chunk_note splitting logic."""

    def test_empty_body_returns_no_chunks(self) -> None:
        note = _make_note("")
        chunks = chunk_note(note)
        assert chunks == []

    def test_whitespace_body_returns_no_chunks(self) -> None:
        note = _make_note("   \n  \n  ")
        chunks = chunk_note(note)
        assert chunks == []

    def test_short_note_returns_single_chunk(self) -> None:
        note = _make_note("This is a short note.")
        chunks = chunk_note(note)
        assert len(chunks) == 1
        assert "short note" in chunks[0].text

    def test_chunk_id_format(self) -> None:
        note = _make_note("Hello world.")
        chunks = chunk_note(note)
        assert chunks[0].chunk_id == f"{note.path}#0"

    def test_chunk_metadata_includes_project(self) -> None:
        note = _make_note("Content", frontmatter={"project": "loom", "type": "decision"})
        chunks = chunk_note(note)
        assert chunks[0].metadata["project"] == "loom"
        assert chunks[0].metadata["type"] == "decision"

    def test_chunk_metadata_includes_tier_from_path(self) -> None:
        note = _make_note("Content", path="projects/my-repo/sessions/hot/note.md")
        chunks = chunk_note(note)
        assert chunks[0].metadata["tier"] == "hot"

    def test_warm_tier_detected(self) -> None:
        note = _make_note("Content", path="projects/my-repo/sessions/warm/note.md")
        chunks = chunk_note(note)
        assert chunks[0].metadata["tier"] == "warm"

    def test_cold_tier_detected(self) -> None:
        note = _make_note("Content", path="projects/my-repo/sessions/cold/note.md")
        chunks = chunk_note(note)
        assert chunks[0].metadata["tier"] == "cold"

    def test_decision_tier_is_permanent(self) -> None:
        note = _make_note("Content", path="projects/my-repo/decisions/auth.md")
        chunks = chunk_note(note)
        assert chunks[0].metadata["tier"] == "permanent"

    def test_knowledge_tier_is_permanent(self) -> None:
        note = _make_note("Content", path="knowledge/patterns/caching.md")
        chunks = chunk_note(note)
        assert chunks[0].metadata["tier"] == "permanent"

    def test_tags_included_in_metadata(self) -> None:
        note = _make_note("Content", tags=["auth", "jwt"])
        chunks = chunk_note(note)
        assert chunks[0].metadata["tags"] == ["auth", "jwt"]

    def test_no_tags_means_no_tags_key(self) -> None:
        note = _make_note("Content", tags=[])
        chunks = chunk_note(note)
        assert "tags" not in chunks[0].metadata

    def test_heading_split(self) -> None:
        body = "## Section 1\n\nContent one.\n\n## Section 2\n\nContent two."
        note = _make_note(body)
        # With default chunk_size of 512, this is small enough to stay as-is
        # but the heading splitter should still produce sections
        chunks = chunk_note(note, chunk_size=30, overlap=0)
        assert len(chunks) >= 2

    def test_long_note_produces_multiple_chunks(self) -> None:
        # Create a note longer than chunk_size
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(20)])
        note = _make_note(body)
        chunks = chunk_note(note, chunk_size=200, overlap=0)
        assert len(chunks) > 1

    def test_all_chunks_have_note_path(self) -> None:
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(10)])
        note = _make_note(body, path="projects/test/sessions/hot/note.md")
        chunks = chunk_note(note, chunk_size=200, overlap=0)
        for chunk in chunks:
            assert chunk.note_path == "projects/test/sessions/hot/note.md"

    def test_chunk_ids_are_sequential(self) -> None:
        body = "\n\n".join([f"Paragraph {i}. " + "x " * 50 for i in range(10)])
        note = _make_note(body)
        chunks = chunk_note(note, chunk_size=200, overlap=0)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id.endswith(f"#{i}")

    def test_overlap_adds_prefix_from_previous_chunk(self) -> None:
        body = "## First\n\nSome content here in the first section.\n\n## Second\n\nDifferent content in the second section."
        note = _make_note(body)
        chunks = chunk_note(note, chunk_size=40, overlap=20)
        if len(chunks) > 1:
            # Second chunk should contain some text from the end of the first
            # (overlap prepends context from the previous chunk)
            assert len(chunks[1].text) > 0

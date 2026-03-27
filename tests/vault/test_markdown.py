"""Tests for loom.vault.markdown — wikilink, frontmatter, and tag parsing."""

from pathlib import Path

from loom.vault.markdown import (
    ParsedNote,
    extract_frontmatter,
    extract_wikilinks,
    parse_note,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "vault"


class TestExtractFrontmatter:
    def test_basic(self) -> None:
        content = "---\ndate: 2026-03-26\nproject: my-repo\n---\n\n# Body"
        fm = extract_frontmatter(content)
        assert fm["date"] == "2026-03-26"
        assert fm["project"] == "my-repo"

    def test_inline_list(self) -> None:
        content = "---\ntags: [loom, session]\n---\n"
        fm = extract_frontmatter(content)
        assert fm["tags"] == ["loom", "session"]

    def test_block_list(self) -> None:
        content = '---\nrelated:\n  - "[[note-a]]"\n  - "[[note-b]]"\n---\n'
        fm = extract_frontmatter(content)
        assert fm["related"] == ["[[note-a]]", "[[note-b]]"]

    def test_no_frontmatter(self) -> None:
        content = "# Just a heading\nSome text."
        assert extract_frontmatter(content) == {}

    def test_empty_frontmatter(self) -> None:
        content = "---\n---\n# Body"
        assert extract_frontmatter(content) == {}


class TestExtractWikilinks:
    def test_simple(self) -> None:
        links = extract_wikilinks("See [[note-a]] and [[note-b]].")
        assert links == ["note-a", "note-b"]

    def test_with_alias(self) -> None:
        links = extract_wikilinks("See [[note-a|my alias]].")
        assert links == ["note-a"]

    def test_nested_path(self) -> None:
        links = extract_wikilinks("[[projects/my-repo/decisions/use-sqlite]]")
        assert links == ["projects/my-repo/decisions/use-sqlite"]

    def test_no_links(self) -> None:
        assert extract_wikilinks("No links here.") == []


class TestParseNote:
    def test_full_note(self) -> None:
        content = (
            FIXTURE_DIR / "projects" / "my-repo" / "session-2026-03-26.md"
        ).read_text()
        note = parse_note("projects/my-repo/session-2026-03-26.md", content)

        assert note.path == "projects/my-repo/session-2026-03-26.md"
        assert note.frontmatter["project"] == "my-repo"
        assert note.frontmatter["type"] == "session"
        assert "loom" in note.tags
        assert "session" in note.tags
        assert "decisions/use-sqlite" in note.wikilinks
        assert "knowledge/tech/python" in note.wikilinks
        assert "## Summary" in note.body

    def test_inline_tags(self) -> None:
        content = (FIXTURE_DIR / "knowledge" / "tech" / "python.md").read_text()
        note = parse_note("knowledge/tech/python.md", content)
        assert "python" in note.tags
        assert "async" in note.tags
        assert "best-practice" in note.tags

    def test_no_frontmatter(self) -> None:
        note = parse_note("plain.md", "# Just a heading\nSome [[link]].")
        assert note.frontmatter == {}
        assert note.wikilinks == ["link"]
        assert note.body == "# Just a heading\nSome [[link]]."

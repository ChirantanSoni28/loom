"""Split vault notes into semantically-aware overlapping chunks for vector embedding."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loom.vault.markdown import ParsedNote

if TYPE_CHECKING:
    from loom.retrieval.embedder import OllamaEmbedder

# Heading with level group and text group captured separately.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    """A text chunk derived from a vault note, ready for embedding.

    chunk_id is content-addressed: {note_path}#{sha256(text)[:8]}.
    This makes chunk IDs stable when unrelated parts of a note change.
    """

    chunk_id: str
    note_path: str
    text: str  # Includes heading breadcrumb prefix when heading_path is set.
    metadata: dict = field(default_factory=dict)


def _content_id(note_path: str, text: str) -> str:
    """Stable, content-addressed chunk ID derived from the chunk's text."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{note_path}#{digest}"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def chunk_note(
    parsed: ParsedNote,
    embedder: OllamaEmbedder | None = None,
    semantic_threshold: float = 0.15,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """Split a parsed note into semantically-aware, content-addressed chunks.

    Strategy (applied in layers):
    1. Structural split: parse body into heading sections, tracking a full
       heading breadcrumb for each section (e.g. "## Arch > ### Decisions").
    2. Semantic split (when embedder is provided): within each section, embed
       each paragraph and insert a split boundary where the cosine similarity
       between adjacent paragraphs drops more than `semantic_threshold` below
       the running mean, or where accumulated size exceeds `chunk_size`.
    3. Size-based split: fallback to greedy paragraph grouping by character
       count when no embedder is available.
    4. Overlap: prepend the tail of the previous chunk to each subsequent
       chunk within the same heading section to preserve local context.

    Each chunk:
    - Carries the heading breadcrumb as a text prefix so the LLM always knows
      where in the note the chunk came from.
    - Has a stable content-addressed ID: {note_path}#{sha256(text)[:8]}.
    - Stores ``parent_chunk_id`` in metadata for child chunks, pointing to the
      first (representative) chunk of their heading section.
    - Stores ``chunk_index`` for ordering.

    Args:
        parsed: A ParsedNote with frontmatter and body.
        embedder: Optional OllamaEmbedder for semantic breakpoint detection.
            When None, falls back to structural splitting.
        semantic_threshold: Relative similarity drop (above the running mean)
            that triggers a semantic split boundary.
        chunk_size: Target chunk size in characters for size-based splitting.
        overlap: Characters of the previous chunk to prepend to the next chunk.

    Returns:
        List of Chunk objects. Returns an empty list if the note body is empty.
    """
    body = parsed.body.strip()
    if not body:
        return []

    metadata = _extract_metadata(parsed)
    sections = _parse_sections(body)
    all_chunks: list[Chunk] = []

    for section in sections:
        heading_path: str = section["heading_path"]
        raw_text: str = section["text"]

        if not raw_text.strip():
            continue

        paragraphs = [p.strip() for p in re.split(r"\n\n+", raw_text) if p.strip()]
        if not paragraphs:
            continue

        if embedder is not None and len(paragraphs) > 1:
            groups = await _semantic_split(
                paragraphs, embedder, semantic_threshold, chunk_size
            )
        else:
            groups = _structural_split(paragraphs, chunk_size)

        groups = _apply_overlap(groups, overlap)

        parent_chunk_id: str | None = None

        for group_text in groups:
            stripped = group_text.strip()
            if not stripped:
                continue

            breadcrumb = f"{heading_path}\n" if heading_path else ""
            full_text = breadcrumb + stripped
            chunk_id = _content_id(parsed.path, full_text)

            chunk_index = len(all_chunks)

            # First chunk in this section is the parent; subsequent chunks reference it.
            if parent_chunk_id is None:
                parent_chunk_id = chunk_id

            chunk_meta: dict = {**metadata, "chunk_index": chunk_index}
            if heading_path:
                chunk_meta["heading_path"] = heading_path
            if chunk_id != parent_chunk_id:
                chunk_meta["parent_chunk_id"] = parent_chunk_id

            all_chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    note_path=parsed.path,
                    text=full_text,
                    metadata=chunk_meta,
                )
            )

    return all_chunks


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def _extract_metadata(parsed: ParsedNote) -> dict:
    """Extract vector store metadata from note frontmatter and path."""
    fm = parsed.frontmatter
    meta: dict = {"note_path": parsed.path}

    for key in ("project", "type", "date"):
        if key in fm:
            meta[key] = fm[key]

    path = parsed.path
    if "/sessions/hot/" in path:
        meta["tier"] = "hot"
    elif "/sessions/warm/" in path:
        meta["tier"] = "warm"
    elif "/sessions/cold/" in path:
        meta["tier"] = "cold"
    elif "/decisions/" in path or path.startswith("knowledge/") or "/knowledge/" in path:
        meta["tier"] = "permanent"

    if parsed.tags:
        meta["tags"] = parsed.tags

    return meta


# ---------------------------------------------------------------------------
# Structural parsing
# ---------------------------------------------------------------------------


def _parse_sections(body: str) -> list[dict]:
    """Parse body into sections, each with a heading breadcrumb and raw text.

    Returns a list of dicts with keys:
        heading_path  — breadcrumb string, e.g. "## Arch > ### Decisions"
                        (empty string for content before the first heading)
        text          — raw text of the section, including the heading line
    """
    sections: list[dict] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if not text:
            return
        path = (
            " > ".join(f"{'#' * lvl} {txt}" for lvl, txt in heading_stack)
            if heading_stack
            else ""
        )
        sections.append({"heading_path": path, "text": text})

    for line in body.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            flush()
            current_lines = [line]
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
        else:
            current_lines.append(line)

    flush()
    return sections


# ---------------------------------------------------------------------------
# Splitting strategies
# ---------------------------------------------------------------------------


async def _semantic_split(
    paragraphs: list[str],
    embedder: OllamaEmbedder,
    threshold: float,
    chunk_size: int,
) -> list[str]:
    """Group paragraphs using embedding-guided breakpoint detection.

    Embeds every paragraph, computes cosine similarity between adjacent pairs,
    and splits where similarity drops more than `threshold` below the running
    mean, or where accumulated character count exceeds `chunk_size`.

    Falls back to structural splitting on any embedding error.
    """
    from loom.retrieval.embedder import OllamaNotAvailableError  # noqa: PLC0415

    try:
        embeddings = await embedder.embed_batch(paragraphs)
    except OllamaNotAvailableError:
        return _structural_split(paragraphs, chunk_size)

    if len(embeddings) != len(paragraphs):
        return _structural_split(paragraphs, chunk_size)

    similarities = [
        _cosine_similarity(embeddings[i], embeddings[i + 1])
        for i in range(len(embeddings) - 1)
    ]

    if not similarities:
        return list(paragraphs)

    mean_sim = sum(similarities) / len(similarities)

    groups: list[str] = []
    current: list[str] = [paragraphs[0]]
    current_len = len(paragraphs[0])

    for i, sim in enumerate(similarities):
        next_para = paragraphs[i + 1]
        next_len = len(next_para)
        is_semantic_break = (mean_sim - sim) > threshold
        is_size_break = current_len + next_len + 2 > chunk_size

        if is_semantic_break or is_size_break:
            groups.append("\n\n".join(current))
            current = [next_para]
            current_len = next_len
        else:
            current.append(next_para)
            current_len += next_len + 2

    if current:
        groups.append("\n\n".join(current))

    return groups


def _structural_split(paragraphs: list[str], chunk_size: int) -> list[str]:
    """Greedily group paragraphs by accumulated character count."""
    groups: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current and current_len + para_len + 2 > chunk_size:
            groups.append("\n\n".join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len + 2

    if current:
        groups.append("\n\n".join(current))

    return groups


def _apply_overlap(groups: list[str], overlap: int) -> list[str]:
    """Prepend overlap characters from the previous group to each group."""
    if overlap <= 0 or len(groups) <= 1:
        return groups

    result: list[str] = [groups[0]]
    for i in range(1, len(groups)):
        prev = groups[i - 1]
        prefix = prev[-overlap:] if len(prev) >= overlap else prev
        space_idx = prefix.find(" ")
        if space_idx >= 0:
            prefix = prefix[space_idx + 1 :]
        result.append(prefix + " " + groups[i])

    return result

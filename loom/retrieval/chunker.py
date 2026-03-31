"""Split vault notes into overlapping chunks for vector embedding."""

import re
from dataclasses import dataclass, field

from loom.vault.markdown import ParsedNote

# Heading pattern: ## or ### etc.
_HEADING_RE = re.compile(r"^(#{1,6})\s+", re.MULTILINE)


@dataclass
class Chunk:
    """A text chunk derived from a vault note, ready for embedding."""

    chunk_id: str          # "{note_path}#{chunk_index}"
    note_path: str
    text: str
    metadata: dict = field(default_factory=dict)


def chunk_note(
    parsed: ParsedNote,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """Split a parsed note into overlapping chunks.

    Prefers splitting at heading boundaries (## lines). Falls back to
    splitting at paragraph boundaries, then at word boundaries.

    Each chunk inherits the note's frontmatter metadata (project, type,
    tier, tags, date) for Pinecone filtering.

    Args:
        parsed: A ParsedNote with frontmatter and body.
        chunk_size: Target chunk size in characters.
        overlap: Number of characters to overlap between chunks.

    Returns:
        List of Chunk objects. Returns a single chunk if the note is
        shorter than chunk_size.
    """
    body = parsed.body.strip()
    if not body:
        return []

    metadata = _extract_metadata(parsed)

    # Split into sections by headings first
    sections = _split_by_headings(body)

    # Further split large sections into chunks
    raw_chunks: list[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            raw_chunks.append(section)
        else:
            raw_chunks.extend(_split_section(section, chunk_size, overlap))

    # Merge very small chunks with their neighbors
    merged = _merge_small_chunks(raw_chunks, chunk_size)

    # Apply overlap
    final = _apply_overlap(merged, overlap)

    return [
        Chunk(
            chunk_id=f"{parsed.path}#{i}",
            note_path=parsed.path,
            text=text.strip(),
            metadata=metadata,
        )
        for i, text in enumerate(final)
        if text.strip()
    ]


def _extract_metadata(parsed: ParsedNote) -> dict:
    """Extract Pinecone-relevant metadata from note frontmatter."""
    fm = parsed.frontmatter
    meta: dict = {"note_path": parsed.path}

    if "project" in fm:
        meta["project"] = fm["project"]
    if "type" in fm:
        meta["type"] = fm["type"]
    if "date" in fm:
        meta["date"] = fm["date"]

    # Infer tier from path
    path = parsed.path
    if "/sessions/hot/" in path:
        meta["tier"] = "hot"
    elif "/sessions/warm/" in path:
        meta["tier"] = "warm"
    elif "/sessions/cold/" in path:
        meta["tier"] = "cold"
    elif "/decisions/" in path:
        meta["tier"] = "permanent"
    elif path.startswith("knowledge/") or "/knowledge/" in path:
        meta["tier"] = "permanent"

    # Tags as a list (Pinecone supports list metadata)
    if parsed.tags:
        meta["tags"] = parsed.tags

    return meta


def _split_by_headings(text: str) -> list[str]:
    """Split text into sections at heading boundaries."""
    parts: list[str] = []
    positions = [m.start() for m in _HEADING_RE.finditer(text)]

    if not positions:
        return [text]

    # Add text before first heading if any
    if positions[0] > 0:
        before = text[: positions[0]].strip()
        if before:
            parts.append(before)

    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        section = text[pos:end].strip()
        if section:
            parts.append(section)

    return parts if parts else [text]


def _split_section(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split a large section into chunks, preferring paragraph boundaries."""
    paragraphs = re.split(r"\n\n+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > chunk_size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2  # +2 for \n\n

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _merge_small_chunks(chunks: list[str], chunk_size: int) -> list[str]:
    """Merge chunks smaller than 1/4 chunk_size with their neighbor."""
    if len(chunks) <= 1:
        return chunks

    min_size = chunk_size // 4
    merged: list[str] = []

    for chunk in chunks:
        if merged and len(merged[-1]) < min_size:
            merged[-1] = merged[-1] + "\n\n" + chunk
        elif merged and len(chunk) < min_size:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)

    return merged


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Prepend overlap characters from the previous chunk to each chunk."""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    result: list[str] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        prefix = prev[-overlap:] if len(prev) >= overlap else prev
        # Find a word boundary in the prefix
        space_idx = prefix.find(" ")
        if space_idx >= 0:
            prefix = prefix[space_idx + 1 :]
        result.append(prefix + " " + chunks[i])

    return result

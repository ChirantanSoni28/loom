"""Parse wikilinks, YAML frontmatter, and tags from Obsidian markdown notes."""

import re
from dataclasses import dataclass, field

# [[link]] or [[link|alias]] — capture the link target (before optional |alias)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# #tag but not inside code fences or frontmatter delimiters
_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z][a-zA-Z0-9_/-]*)", re.MULTILINE)

# YAML frontmatter block: starts and ends with ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class ParsedNote:
    """Structured representation of an Obsidian note."""

    path: str
    frontmatter: dict = field(default_factory=dict)
    wikilinks: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    body: str = ""


def extract_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from the top of a markdown file.

    Returns an empty dict if no frontmatter is found.
    Uses a simple key-value parser to avoid a PyYAML dependency.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    raw = match.group(1)
    result: dict = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for inline list: key: [val1, val2]
        if ":" in stripped and current_list is None:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value.startswith("[") and value.endswith("]"):
                # Inline list
                items = [
                    item.strip().strip("\"'")
                    for item in value[1:-1].split(",")
                    if item.strip()
                ]
                result[key] = items
                current_key = None
                current_list = None
            elif value == "":
                # Start of a block list or nested value
                current_key = key
                current_list = []
            else:
                result[key] = value.strip("\"'")
                current_key = None
                current_list = None
        elif stripped.startswith("- ") and current_key is not None and current_list is not None:
            item = stripped[2:].strip().strip("\"'")
            current_list.append(item)
        else:
            # Continuation or unknown format — skip
            continue

    # Flush any remaining list
    if current_key is not None and current_list is not None:
        result[current_key] = current_list

    return result


def extract_wikilinks(content: str) -> list[str]:
    """Extract all [[wikilink]] targets from markdown content."""
    return _WIKILINK_RE.findall(content)


def _extract_inline_tags(content: str) -> list[str]:
    """Extract #tags from the body of a note (not from frontmatter)."""
    return _TAG_RE.findall(content)


def parse_note(path: str, content: str) -> ParsedNote:
    """Parse an Obsidian markdown note into structured components."""
    frontmatter = extract_frontmatter(content)

    # Body is everything after frontmatter
    fm_match = _FRONTMATTER_RE.match(content)
    body = content[fm_match.end() :] if fm_match else content

    wikilinks = extract_wikilinks(content)

    # Tags from frontmatter + inline
    fm_tags_raw = frontmatter.get("tags", [])
    if isinstance(fm_tags_raw, str):
        fm_tags = [fm_tags_raw]
    else:
        fm_tags = list(fm_tags_raw)
    inline_tags = _extract_inline_tags(body)

    # Deduplicate while preserving order
    seen: set[str] = set()
    all_tags: list[str] = []
    for tag in fm_tags + inline_tags:
        if tag not in seen:
            seen.add(tag)
            all_tags.append(tag)

    return ParsedNote(
        path=path,
        frontmatter=frontmatter,
        wikilinks=wikilinks,
        tags=all_tags,
        body=body,
    )

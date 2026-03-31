"""Extract decisions and patterns from session notes before compression."""

import re
from pathlib import Path

from loom.vault import VaultClient


async def extract_decisions(
    session_contents: list[str],
    project: str,
    client: VaultClient,
) -> list[str]:
    """Extract decisions from session notes and write to decisions/.

    Scans for "Key Decisions" or "## Key Decisions" sections in session
    notes. Each decision not already in decisions/ gets a separate note.

    Args:
        session_contents: List of session note markdown contents.
        project: Project name.
        client: VaultClient for reading/writing.

    Returns:
        List of vault paths for newly created decision notes.
    """
    created: list[str] = []

    # Load existing decision titles to avoid duplicates
    existing_titles: set[str] = set()
    decisions_dir = f"projects/{project}/decisions"
    try:
        files = await client.list_directory(decisions_dir)
        for f in files:
            if f.endswith(".md"):
                existing_titles.add(Path(f).stem.lower())
    except (FileNotFoundError, Exception):
        pass

    for content in session_contents:
        decisions = _parse_decisions_section(content)
        for title, body in decisions:
            slug = _slugify(title)
            if slug.lower() in existing_titles:
                continue

            dec_path = f"{decisions_dir}/{slug}.md"
            fm = f"---\ntype: decision\nproject: {project}\n---\n\n"
            await client.write_note(dec_path, fm + f"# {title}\n\n{body}")
            created.append(dec_path)
            existing_titles.add(slug.lower())

    return created


async def extract_patterns(
    session_contents: list[str],
    client: VaultClient,
) -> list[str]:
    """Detect recurring patterns across sessions and write to knowledge/.

    Looks for repeated file paths, tool usage, or approaches across
    multiple sessions.

    Args:
        session_contents: List of session note markdown contents.
        client: VaultClient for writing.

    Returns:
        List of vault paths for newly created pattern notes.
    """
    # Count file path occurrences across sessions
    file_counts: dict[str, int] = {}
    for content in session_contents:
        files = _extract_files_changed(content)
        for f in files:
            file_counts[f] = file_counts.get(f, 0) + 1

    # Files appearing in 3+ sessions might be a pattern
    created: list[str] = []
    frequent_files = {f: c for f, c in file_counts.items() if c >= 3}

    if frequent_files:
        slug = "frequently-modified-files"
        pattern_path = f"knowledge/patterns/{slug}.md"

        lines = ["# Frequently Modified Files\n"]
        for f, count in sorted(frequent_files.items(), key=lambda x: -x[1]):
            lines.append(f"- `{f}` ({count} sessions)")

        try:
            existing = await client.read_note(pattern_path)
            # Update existing note
            await client.write_note(pattern_path, "\n".join(lines) + "\n")
        except (FileNotFoundError, Exception):
            fm = "---\ntype: pattern\n---\n\n"
            await client.write_note(pattern_path, fm + "\n".join(lines) + "\n")

        created.append(pattern_path)

    return created


def _parse_decisions_section(content: str) -> list[tuple[str, str]]:
    """Parse decision items from a session note's Key Decisions section.

    Returns:
        List of (title, body) tuples.
    """
    # Find the Key Decisions section
    match = re.search(r"## Key Decisions\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not match:
        return []

    section = match.group(1).strip()
    decisions: list[tuple[str, str]] = []

    # Parse bullet points: - **Title**: description
    for m in re.finditer(r"-\s+\*\*(.+?)\*\*:\s*(.+)", section):
        title = m.group(1).strip()
        body = m.group(2).strip()
        decisions.append((title, body))

    return decisions


def _extract_files_changed(content: str) -> list[str]:
    """Extract file paths from the Files Changed section."""
    match = re.search(r"## Files Changed\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not match:
        return []

    files: list[str] = []
    for m in re.finditer(r"-\s+`(.+?)`", match.group(1)):
        files.append(m.group(1))
    return files


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-.")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80]

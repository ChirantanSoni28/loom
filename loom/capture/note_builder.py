"""Assemble structured markdown session notes from buffered events."""

import json
from collections import OrderedDict

from loom.capture.buffer import BufferedEvent


def build_session_note(
    events: list[BufferedEvent],
    project: str,
    date: str,
    repo_path: str,
) -> str:
    """Build a structured markdown session note from buffered events.

    Sections:
    - Frontmatter (YAML)
    - Summary (auto-generated from event counts)
    - Key Decisions (decision_signal events)
    - Files Changed (file_edit events, deduplicated)
    - Commands Run (bash_command events, filtered)
    - Errors Resolved (error_resolution events)

    Args:
        events: Chronologically ordered list of buffered events.
        project: Repository/project name.
        date: ISO date string (e.g. "2026-03-30").
        repo_path: Absolute path to the repository.

    Returns:
        Complete markdown string ready to write to the vault.
    """
    decisions = [e for e in events if e.event_type == "decision_signal"]
    file_edits = [e for e in events if e.event_type == "file_edit"]
    bash_commands = [e for e in events if e.event_type == "bash_command"]
    error_resolutions = [e for e in events if e.event_type == "error_resolution"]

    # Deduplicate file paths while preserving order
    changed_files = _deduplicate_file_paths(file_edits)

    sections: list[str] = []

    # Frontmatter
    related_links = _extract_related_links(decisions)
    fm = _build_frontmatter(project, date, related_links)
    sections.append(fm)

    # Title
    sections.append(f"# Session: {date}")

    # Summary
    summary = _build_summary(
        len(decisions), len(changed_files), len(bash_commands), len(error_resolutions),
    )
    sections.append(f"## Summary\n\n{summary}")

    # Key Decisions
    if decisions:
        decision_lines = _format_decisions(decisions)
        sections.append(f"## Key Decisions\n\n{decision_lines}")

    # Files Changed
    if changed_files:
        file_lines = "\n".join(f"- `{f}`" for f in changed_files)
        sections.append(f"## Files Changed\n\n{file_lines}")

    # Commands Run
    if bash_commands:
        cmd_lines = _format_bash_commands(bash_commands)
        sections.append(f"## Commands Run\n\n{cmd_lines}")

    # Errors Resolved
    if error_resolutions:
        error_lines = _format_error_resolutions(error_resolutions)
        sections.append(f"## Errors Resolved\n\n{error_lines}")

    return "\n\n".join(sections) + "\n"


def extract_decisions(events: list[BufferedEvent]) -> list[dict]:
    """Extract decision events into structured dicts for separate decision notes.

    Args:
        events: All buffered events for the session.

    Returns:
        List of dicts with 'title', 'content', and 'related' keys.
    """
    decisions = [e for e in events if e.event_type == "decision_signal"]
    result: list[dict] = []

    for event in decisions:
        title = _decision_title(event)
        content = _decision_content(event)
        result.append({
            "title": title,
            "content": content,
            "related": [],
        })

    return result


def _build_frontmatter(project: str, date: str, related: list[str]) -> str:
    """Build YAML frontmatter block."""
    lines = [
        "---",
        "type: session",
        f"project: {project}",
        f"date: {date}",
    ]
    if related:
        lines.append(f"related: {json.dumps(related)}")
    lines.append("---")
    return "\n".join(lines)


def _build_summary(
    decision_count: int,
    file_count: int,
    command_count: int,
    error_count: int,
) -> str:
    """Generate a summary line from event counts."""
    parts: list[str] = []
    if file_count:
        parts.append(f"{file_count} file{'s' if file_count != 1 else ''} changed")
    if decision_count:
        parts.append(f"{decision_count} decision{'s' if decision_count != 1 else ''} made")
    if command_count:
        parts.append(f"{command_count} command{'s' if command_count != 1 else ''} run")
    if error_count:
        parts.append(f"{error_count} error{'s' if error_count != 1 else ''} resolved")

    if not parts:
        return "No significant activity captured."

    return "Session activity: " + ", ".join(parts) + "."


def _deduplicate_file_paths(file_edits: list[BufferedEvent]) -> list[str]:
    """Extract unique file paths from file edit events, preserving order."""
    seen: OrderedDict[str, None] = OrderedDict()
    for event in file_edits:
        path = event.tool_input.get("file_path", event.tool_input.get("path", ""))
        if path:
            seen[path] = None
    return list(seen.keys())


def _extract_related_links(decisions: list[BufferedEvent]) -> list[str]:
    """Extract wikilink-style references from decision events."""
    links: list[str] = []
    for event in decisions:
        title = _decision_title(event)
        slug = _slugify(title)
        links.append(f"[[decisions/{slug}]]")
    return links


def _format_decisions(decisions: list[BufferedEvent]) -> str:
    """Format decision events as a markdown list."""
    lines: list[str] = []
    for event in decisions:
        title = _decision_title(event)
        content = _decision_summary(event)
        lines.append(f"- **{title}**: {content}")
    return "\n".join(lines)


def _format_bash_commands(commands: list[BufferedEvent]) -> str:
    """Format bash command events as a markdown list."""
    lines: list[str] = []
    for event in commands:
        cmd = event.tool_input.get("command", "")
        # Truncate long commands
        if len(cmd) > 120:
            cmd = cmd[:117] + "..."
        lines.append(f"- `{cmd}`")
    return "\n".join(lines)


def _format_error_resolutions(errors: list[BufferedEvent]) -> str:
    """Format error resolution events as a markdown list."""
    lines: list[str] = []
    for event in errors:
        tool = event.tool_name
        desc = str(event.tool_response)[:200]
        lines.append(f"- **{tool}**: {desc}")
    return "\n".join(lines)


def _decision_title(event: BufferedEvent) -> str:
    """Derive a short title from a decision event."""
    # Try to use file path if it's a file edit decision
    file_path = event.tool_input.get("file_path", "")
    if file_path:
        return f"Change to {file_path.split('/')[-1]}"

    # For bash commands, use a truncated command
    command = event.tool_input.get("command", "")
    if command:
        short = command.strip().split("\n")[0][:60]
        return f"Command: {short}"

    return f"Decision in {event.tool_name}"


def _decision_content(event: BufferedEvent) -> str:
    """Build markdown content for a standalone decision note."""
    lines = [f"## Context\n\nTool: `{event.tool_name}`"]

    input_summary = json.dumps(event.tool_input, indent=2)
    if len(input_summary) > 500:
        input_summary = input_summary[:497] + "..."
    lines.append(f"### Input\n\n```json\n{input_summary}\n```")

    response_summary = json.dumps(event.tool_response, indent=2)
    if len(response_summary) > 500:
        response_summary = response_summary[:497] + "..."
    lines.append(f"### Response\n\n```json\n{response_summary}\n```")

    return "\n\n".join(lines)


def _decision_summary(event: BufferedEvent) -> str:
    """One-line summary of a decision event for the session note."""
    # Try to extract meaningful text from the tool input
    for key in ("content", "command", "description"):
        val = event.tool_input.get(key, "")
        if val:
            short = str(val).strip().split("\n")[0][:100]
            return short
    return f"via {event.tool_name}"


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower()
    slug = slug.replace(" ", "-")
    # Keep only alphanumeric, hyphens, dots
    slug = "".join(c for c in slug if c.isalnum() or c in "-.")
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80]

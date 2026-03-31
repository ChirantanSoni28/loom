"""Capture engine — orchestrates event buffering, note building, and vault writes."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from loom.capture.buffer import BufferedEvent, buffer_event, clear_events, load_events
from loom.capture.classifier import EventType
from loom.capture.note_builder import build_session_note, extract_decisions
from loom.config import LoomConfig, load_config
from loom.vault import VaultClient


class CaptureEngine:
    """Orchestrates the capture pipeline: buffer → classify → build → write.

    Used by CLI hooks:
    - ``handle_post_tool_use``: called by PostToolUse hook to buffer an event
    - ``handle_flush``: called by Stop hook to build and write session notes
    """

    def __init__(self, config: LoomConfig | None = None) -> None:
        self._config = config or load_config()

    # ------------------------------------------------------------------
    # PostToolUse hook
    # ------------------------------------------------------------------

    def handle_post_tool_use(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
        tool_response: dict,
    ) -> EventType:
        """Buffer a single tool event. Called by the PostToolUse hook.

        Args:
            session_id: Current session identifier.
            tool_name: Name of the tool that was invoked.
            tool_input: Input parameters.
            tool_response: Tool response.

        Returns:
            The EventType assigned to this event.
        """
        return buffer_event(session_id, tool_name, tool_input, tool_response)

    # ------------------------------------------------------------------
    # Stop hook (flush)
    # ------------------------------------------------------------------

    async def handle_flush(
        self,
        session_id: str,
        repo_path: str,
    ) -> dict:
        """Flush buffered events into vault notes. Called by the Stop hook.

        Builds a session note and any decision notes, writes them to the
        vault, and clears the event buffer.

        Args:
            session_id: Session to flush.
            repo_path: Absolute path to the repository.

        Returns:
            Dict with written file paths and counts.
        """
        events = load_events(session_id)

        if not events:
            return {"status": "empty", "session_note": None, "decisions": []}

        project = Path(repo_path).name
        date = datetime.now(UTC).strftime("%Y-%m-%d")

        # Build session note
        session_md = build_session_note(events, project, date, repo_path)

        # Auto-link: wrap known vault note titles in [[wikilinks]]
        session_md = await self._auto_link(session_md)

        # Write session note to vault
        session_path = f"projects/{project}/sessions/hot/{date}.md"
        async with VaultClient(self._config) as client:
            await client.write_note(session_path, session_md)

            # Extract and write decision notes
            decisions = extract_decisions(events)
            decision_paths: list[str] = []
            for decision in decisions:
                slug = _slugify(decision["title"])
                dec_path = f"projects/{project}/decisions/{slug}.md"
                now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                fm = "\n".join([
                    "---",
                    "type: decision",
                    f"project: {project}",
                    f"created: {now}",
                    f"related: {json.dumps(decision['related'])}",
                    "---",
                ])
                dec_content = fm + "\n\n" + decision["content"]
                dec_content = await self._auto_link(dec_content)
                await client.write_note(dec_path, dec_content)
                decision_paths.append(dec_path)

        # Clear buffer
        clear_events(session_id)

        return {
            "status": "flushed",
            "session_note": session_path,
            "decisions": decision_paths,
        }

    # ------------------------------------------------------------------
    # Auto-linking
    # ------------------------------------------------------------------

    async def _auto_link(self, content: str) -> str:
        """Wrap known vault note titles in [[wikilinks]].

        Scans the vault for existing note titles and replaces verbatim
        occurrences in the content with wikilinks.
        """
        try:
            async with VaultClient(self._config) as client:
                titles = await self._collect_vault_titles(client)
        except Exception:
            return content

        if not titles:
            return content

        # Sort by length descending so longer titles match first
        sorted_titles = sorted(titles.keys(), key=len, reverse=True)

        for title in sorted_titles:
            vault_path = titles[title]
            # Don't match inside existing wikilinks or frontmatter
            pattern = re.compile(
                r"(?<!\[\[)"  # not already inside a wikilink
                + re.escape(title)
                + r"(?!\]\])",  # not already closing a wikilink
                re.IGNORECASE,
            )
            content = pattern.sub(f"[[{vault_path}|{title}]]", content, count=1)

        return content

    async def _collect_vault_titles(self, client: VaultClient) -> dict[str, str]:
        """Build a mapping of note titles → vault-relative paths."""
        titles: dict[str, str] = {}

        for directory in ("projects", "knowledge"):
            try:
                await self._walk_titles(client, directory, titles)
            except (FileNotFoundError, Exception):
                continue

        return titles

    async def _walk_titles(
        self,
        client: VaultClient,
        directory: str,
        titles: dict[str, str],
    ) -> None:
        """Recursively collect note titles from a vault directory."""
        try:
            files = await client.list_directory(directory)
        except (FileNotFoundError, Exception):
            return

        for f in files:
            path = f if f.startswith(directory) else f"{directory}/{f}"
            if path.endswith(".md"):
                title = Path(path).stem
                # Skip very short titles that would cause false positives
                if len(title) > 3:
                    titles[title] = path
            else:
                # Try as subdirectory
                await self._walk_titles(client, path, titles)


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-.")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80]

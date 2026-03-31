"""LLM-based rollup summarization using Claude API."""

import anthropic


async def summarize_hot_to_warm(
    sessions: list[str],
    project: str,
    week: str,
    anthropic_key: str,
) -> str:
    """Summarize a week's hot sessions into a warm rollup note.

    Uses claude-haiku-4-5 to produce a concise weekly summary that
    preserves key decisions and wikilinks.

    Args:
        sessions: List of session note markdown contents.
        project: Project name.
        week: ISO week identifier (e.g. "2026-W13").
        anthropic_key: Anthropic API key.

    Returns:
        Markdown string for the warm rollup note (without frontmatter).
    """
    combined = "\n\n---\n\n".join(sessions)

    client = anthropic.Anthropic(api_key=anthropic_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"You are summarizing a week of Claude Code sessions for project '{project}' (week {week}).\n\n"
                    "Create a concise weekly rollup (200-400 words) with these sections:\n"
                    "- ## Summary (1-2 paragraphs of what was accomplished)\n"
                    "- ## Key Decisions (bullet points, preserve any [[wikilinks]])\n"
                    "- ## Patterns Observed (if any recurring approaches)\n"
                    "- ## Files Changed (deduplicated list)\n\n"
                    "Preserve all [[wikilinks]] from the source sessions.\n\n"
                    f"Session notes:\n\n{combined}"
                ),
            }
        ],
    )

    return message.content[0].text


async def summarize_warm_to_cold(
    rollups: list[str],
    project: str,
    quarter: str,
    anthropic_key: str,
) -> str:
    """Summarize warm rollups into a quarterly cold digest.

    Uses claude-haiku-4-5 to produce a high-level quarterly summary
    highlighting major themes and architectural changes.

    Args:
        rollups: List of warm rollup note markdown contents.
        project: Project name.
        quarter: Quarter identifier (e.g. "2026-Q1").
        anthropic_key: Anthropic API key.

    Returns:
        Markdown string for the cold digest note (without frontmatter).
    """
    combined = "\n\n---\n\n".join(rollups)

    client = anthropic.Anthropic(api_key=anthropic_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"You are creating a quarterly digest for project '{project}' ({quarter}).\n\n"
                    "Create a high-level digest (300-500 words) with these sections:\n"
                    "- ## Quarter Overview (1-2 paragraphs of major themes)\n"
                    "- ## Key Decisions (most important decisions, preserve [[wikilinks]])\n"
                    "- ## Architectural Changes (what changed in the codebase structure)\n"
                    "- ## Recurring Patterns (tools, files, approaches used repeatedly)\n\n"
                    "Preserve all [[wikilinks]] from the source rollups.\n\n"
                    f"Weekly rollups:\n\n{combined}"
                ),
            }
        ],
    )

    return message.content[0].text

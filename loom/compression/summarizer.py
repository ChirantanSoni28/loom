"""LLM-based rollup summarization with pluggable provider support."""

import httpx


_HOT_TO_WARM_PROMPT = """\
You are summarizing a week of Claude Code sessions for project '{project}' (week {week}).

Create a concise weekly rollup (200-400 words) with these sections:
- ## Summary (1-2 paragraphs of what was accomplished)
- ## Key Decisions (bullet points, preserve any [[wikilinks]])
- ## Patterns Observed (if any recurring approaches)
- ## Files Changed (deduplicated list)

Preserve all [[wikilinks]] from the source sessions.

Session notes:

{combined}"""

_WARM_TO_COLD_PROMPT = """\
You are creating a quarterly digest for project '{project}' ({quarter}).

Create a high-level digest (300-500 words) with these sections:
- ## Quarter Overview (1-2 paragraphs of major themes)
- ## Key Decisions (most important decisions, preserve [[wikilinks]])
- ## Architectural Changes (what changed in the codebase structure)
- ## Recurring Patterns (tools, files, approaches used repeatedly)

Preserve all [[wikilinks]] from the source rollups.

Weekly rollups:

{combined}"""


async def summarize_hot_to_warm(
    sessions: list[str],
    project: str,
    week: str,
    provider: str,
    model: str,
    ollama_base_url: str,
    anthropic_key: str | None = None,
) -> str:
    """Summarize a week's hot sessions into a warm rollup note.

    Dispatches to Ollama or Anthropic based on provider.

    Args:
        sessions: List of session note markdown contents.
        project: Project name.
        week: ISO week identifier (e.g. "2026-W13").
        provider: LLM provider — "ollama" or "anthropic".
        model: Chat model name.
        ollama_base_url: Base URL for Ollama API (e.g. "http://localhost:11434").
        anthropic_key: Anthropic API key (required only when provider="anthropic").

    Returns:
        Markdown string for the warm rollup note (without frontmatter).
    """
    combined = "\n\n---\n\n".join(sessions)
    prompt = _HOT_TO_WARM_PROMPT.format(project=project, week=week, combined=combined)
    return await _call_llm(provider, model, ollama_base_url, anthropic_key, prompt)


async def summarize_warm_to_cold(
    rollups: list[str],
    project: str,
    quarter: str,
    provider: str,
    model: str,
    ollama_base_url: str,
    anthropic_key: str | None = None,
) -> str:
    """Summarize warm rollups into a quarterly cold digest.

    Dispatches to Ollama or Anthropic based on provider.

    Args:
        rollups: List of warm rollup note markdown contents.
        project: Project name.
        quarter: Quarter identifier (e.g. "2026-Q1").
        provider: LLM provider — "ollama" or "anthropic".
        model: Chat model name.
        ollama_base_url: Base URL for Ollama API (e.g. "http://localhost:11434").
        anthropic_key: Anthropic API key (required only when provider="anthropic").

    Returns:
        Markdown string for the cold digest note (without frontmatter).
    """
    combined = "\n\n---\n\n".join(rollups)
    prompt = _WARM_TO_COLD_PROMPT.format(project=project, quarter=quarter, combined=combined)
    return await _call_llm(provider, model, ollama_base_url, anthropic_key, prompt)


async def _call_llm(
    provider: str,
    model: str,
    ollama_base_url: str,
    anthropic_key: str | None,
    prompt: str,
) -> str:
    """Dispatch a single-turn prompt to the configured LLM provider.

    Args:
        provider: "ollama" or "anthropic".
        model: Chat model name.
        ollama_base_url: Base URL for Ollama API.
        anthropic_key: Anthropic API key (only used when provider="anthropic").
        prompt: The user-role message to send.

    Returns:
        The model's text response.

    Raises:
        ValueError: If provider is "anthropic" and no API key is configured.
        ValueError: If an unknown provider is specified.
    """
    if provider == "ollama":
        return await _call_ollama(ollama_base_url, model, prompt)
    elif provider == "anthropic":
        if not anthropic_key:
            raise ValueError(
                "compression_anthropic_key must be set when compression_llm_provider is 'anthropic'.\n"
                "Run: loom config set compression_anthropic_key <your-key>"
            )
        return await _call_anthropic(anthropic_key, model, prompt)
    else:
        raise ValueError(
            f"Unknown compression LLM provider: {provider!r}. "
            "Valid values: 'ollama', 'anthropic'."
        )


async def _call_ollama(base_url: str, model: str, prompt: str) -> str:
    """Call Ollama's /api/chat endpoint."""
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    return data["message"]["content"]


async def _call_anthropic(api_key: str, model: str, prompt: str) -> str:
    """Call the Anthropic Messages API."""
    import anthropic  # lazy import — only required when provider="anthropic"

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text

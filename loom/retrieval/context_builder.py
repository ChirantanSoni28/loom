"""Format hybrid search results into Claude-friendly context with citations."""

from loom.retrieval.hybrid import HybridResult


def build_context(results: list[HybridResult], token_budget: int = 4000) -> str:
    """Convert search results into readable context for Claude.

    Formats results as numbered markdown sections with excerpts,
    truncated to fit within the token budget.

    Args:
        results: Ranked HybridResult list from hybrid_search.
        token_budget: Approximate token budget (estimated as len/4).

    Returns:
        Markdown string with citations.
    """
    if not results:
        return "_No relevant context found in vault._"

    sections: list[str] = ["## Relevant Context from Vault\n"]
    used_tokens = 10  # header overhead

    for i, r in enumerate(results, 1):
        source = "via graph" if r.graph_hops > 0 else "vector"
        header = f"### [{i}] {r.path} (score: {r.score:.2f}, {source})"

        excerpt = r.excerpt.strip()
        if not excerpt:
            excerpt = "_No content available._"

        # Metadata line
        meta_parts: list[str] = []
        if r.metadata.get("tags"):
            meta_parts.append(f"Tags: {', '.join(r.metadata['tags'])}")
        if r.metadata.get("type"):
            meta_parts.append(f"Type: {r.metadata['type']}")
        if r.metadata.get("tier"):
            meta_parts.append(f"Tier: {r.metadata['tier']}")

        meta_line = f"*{' | '.join(meta_parts)}*" if meta_parts else ""

        section = f"{header}\n> {excerpt}"
        if meta_line:
            section += f"\n> {meta_line}"

        section_tokens = len(section) // 4
        if used_tokens + section_tokens > token_budget and i > 1:
            break

        sections.append(section)
        used_tokens += section_tokens

    sections.append(f"\n[{len(sections) - 1} results | ~{used_tokens} tokens]")

    return "\n\n".join(sections)

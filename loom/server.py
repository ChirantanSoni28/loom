"""Loom MCP server — tools and resources for vault-backed memory."""

import json
from datetime import UTC, datetime
from pathlib import Path

from mcp.server import FastMCP

from loom.config import load_config
from loom.vault import VaultClient

server = FastMCP("loom")


def _repo_name_from_path(repo_path: str) -> str:
    """Extract the repository name from an absolute path."""
    return Path(repo_path).name


async def _get_vault_client() -> VaultClient:
    """Create and initialize a VaultClient from current config."""
    config = load_config()
    client = VaultClient(config)
    await client.__aenter__()
    return client


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@server.tool()
async def loom_context(repo_path: str) -> str:
    """Load project context at session start.

    Returns architecture.md, recent hot sessions, and key decisions
    for the given repository path.
    """
    project = _repo_name_from_path(repo_path)
    client = await _get_vault_client()

    sections: list[str] = [f"## Project: {project}"]

    # Architecture
    arch_path = f"projects/{project}/architecture.md"
    try:
        arch_content = await client.read_note(arch_path)
        sections.append(f"### Architecture\n{arch_content}")
    except (FileNotFoundError, Exception):
        sections.append("### Architecture\n_No architecture.md found yet._")

    # Recent sessions (hot tier — last 3)
    sessions_path = f"projects/{project}/sessions/hot"
    try:
        files = await client.list_directory(sessions_path)
        # Sort descending by name (dates sort lexicographically)
        md_files = sorted(
            [f for f in files if f.endswith(".md")],
            reverse=True,
        )[:3]
        if md_files:
            excerpts: list[str] = []
            for f in md_files:
                note_path = f if f.startswith("projects/") else f"{sessions_path}/{f}"
                try:
                    content = await client.read_note(note_path)
                    # Truncate to first 500 chars for context window budget
                    excerpt = content[:500]
                    if len(content) > 500:
                        excerpt += "\n..."
                    excerpts.append(f"#### {Path(f).stem}\n{excerpt}")
                except (FileNotFoundError, Exception):
                    continue
            sections.append("### Recent Sessions (last 3)\n" + "\n\n".join(excerpts))
        else:
            sections.append("### Recent Sessions\n_No sessions recorded yet._")
    except (FileNotFoundError, Exception):
        sections.append("### Recent Sessions\n_No sessions recorded yet._")

    # Key decisions
    decisions_path = f"projects/{project}/decisions"
    try:
        files = await client.list_directory(decisions_path)
        md_files = [f for f in files if f.endswith(".md")]
        if md_files:
            items: list[str] = []
            for f in md_files:
                note_path = f if f.startswith("projects/") else f"{decisions_path}/{f}"
                items.append(f"- [[{note_path}|{Path(f).stem}]]")
            sections.append("### Key Decisions\n" + "\n".join(items))
        else:
            sections.append("### Key Decisions\n_No decisions recorded yet._")
    except (FileNotFoundError, Exception):
        sections.append("### Key Decisions\n_No decisions recorded yet._")

    # Compression notification
    try:
        config = load_config()
        if config.compression_enabled:
            from loom.compression.scheduler import check_compression

            report = await check_compression(project, config, client)
            if report.hot_ready or report.warm_ready:
                count = len(report.hot_ready) + len(report.warm_ready)
                sections.append(
                    f"---\n"
                    f"Loom: {count} session(s) are ready to compress.\n"
                    f"Run `loom_compress` tool to proceed, or ignore to keep sessions as-is.\n"
                    f"(Disable: set compression.enabled=false in loom-settings.json)"
                )
    except Exception:
        pass  # Don't block context loading

    return "\n\n".join(sections)


@server.tool()
async def loom_capture(
    type: str,
    project: str,
    title: str,
    content: str,
    related: list[str] | None = None,
) -> str:
    """Write a session note or decision to the vault.

    Args:
        type: Note type — "session" or "decision".
        project: Repository/project name.
        title: Note title (used as filename).
        content: Markdown body of the note.
        related: Optional list of wikilinks to related notes.
    """
    client = await _get_vault_client()

    # Build vault-relative path
    if type == "decision":
        vault_path = f"projects/{project}/decisions/{title}.md"
    else:
        # Default to session in hot tier
        vault_path = f"projects/{project}/sessions/hot/{title}.md"

    # Build frontmatter
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fm_lines = [
        "---",
        f"type: {type}",
        f"project: {project}",
        f"created: {now}",
    ]
    if related:
        fm_lines.append(f"related: {json.dumps(related)}")
    fm_lines.append("---")

    full_content = "\n".join(fm_lines) + "\n\n" + content

    await client.write_note(vault_path, full_content)

    return json.dumps({"path": vault_path, "status": "written"})


@server.tool()
async def loom_search(
    query: str,
    project: str | None = None,
    limit: int = 5,
) -> str:
    """Search the vault using hybrid vector + graph retrieval.

    Combines semantic vector search (ChromaDB) with graph expansion
    (wikilink BFS) and reranks results. Falls back to keyword search
    if vector search is unavailable.

    Args:
        query: Search query string.
        project: Optional project name to scope the search.
        limit: Maximum number of results to return.
    """
    config = load_config()

    # Try hybrid search (vector + graph)
    try:
        from loom.retrieval.context_builder import build_context
        from loom.retrieval.hybrid import hybrid_search

        results = await hybrid_search(query, config, project=project, limit=limit)
        if results:
            return build_context(results)
    except Exception:
        pass  # Fall through to keyword search

    # Fallback: keyword search via VaultClient
    client = await _get_vault_client()
    results_kw = await client.search(query)

    if project:
        prefix = f"projects/{project}/"
        results_kw = [r for r in results_kw if r.path.startswith(prefix)]

    results_kw = results_kw[:limit]

    output = [
        {
            "path": r.path,
            "score": r.score if hasattr(r, "score") else 1.0,
            "excerpt": r.excerpt if hasattr(r, "excerpt") else "",
        }
        for r in results_kw
    ]

    return json.dumps(output)


@server.tool()
async def loom_relate(path: str, depth: int = 2) -> str:
    """Find notes connected to a given note via wikilinks.

    Traverses the wikilink graph (both forward links and backlinks)
    using BFS up to the specified depth.

    Args:
        path: Vault-relative path of the source note.
        depth: Maximum link hops to traverse (default 2).
    """
    from loom.db import get_connection
    from loom.retrieval.graph import VaultGraph

    db = get_connection()
    try:
        graph = VaultGraph(db)
        nodes = graph.bfs([path], max_depth=depth)
        return json.dumps([{"path": n.path, "hops": n.hops} for n in nodes])
    finally:
        db.close()


@server.tool()
async def loom_compress(project: str, dry_run: bool = True) -> str:
    """Trigger compression for a project's session notes.

    Checks hot and warm tiers for notes past their TTL. If dry_run is
    False and compression is enabled, runs hot→warm rollup using Claude
    API for summarization.

    Args:
        project: Project name to compress.
        dry_run: If True, only report what would be compressed.
    """
    config = load_config()
    client = await _get_vault_client()

    from loom.compression.scheduler import check_compression, run_hot_to_warm, run_warm_to_cold

    report = await check_compression(project, config, client)

    if dry_run or not report.can_compress:
        return json.dumps({
            "project": project,
            "hot_ready": len(report.hot_ready),
            "warm_ready": len(report.warm_ready),
            "can_compress": report.can_compress,
            "requires_approval": report.requires_approval,
            "status": "dry_run",
        })

    result: dict = {"project": project, "status": "done"}

    # Run hot→warm compression
    if report.hot_ready:
        warm_path = await run_hot_to_warm(project, report.hot_ready, config, client)
        result["warm_rollup"] = warm_path
        result["hot_compressed"] = len(report.hot_ready)

    # Run warm→cold compression
    if report.warm_ready:
        cold_path = await run_warm_to_cold(project, report.warm_ready, config, client)
        result["cold_digest"] = cold_path
        result["warm_compressed"] = len(report.warm_ready)

    return json.dumps(result)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@server.resource("loom://project/{repo}")
async def project_overview(repo: str) -> str:
    """Returns architecture.md for the given repo."""
    client = await _get_vault_client()
    arch_path = f"projects/{repo}/architecture.md"
    try:
        return await client.read_note(arch_path)
    except (FileNotFoundError, Exception):
        return f"No architecture.md found for project '{repo}'."


@server.resource("loom://knowledge/preferences")
async def user_preferences() -> str:
    """Returns all notes from knowledge/preferences/."""
    client = await _get_vault_client()
    try:
        files = await client.list_directory("knowledge/preferences")
        md_files = [f for f in files if f.endswith(".md")]
        if not md_files:
            return "_No preference notes found._"

        sections: list[str] = []
        for f in md_files:
            note_path = (
                f if f.startswith("knowledge/") else f"knowledge/preferences/{f}"
            )
            try:
                content = await client.read_note(note_path)
                sections.append(f"## {Path(f).stem}\n{content}")
            except (FileNotFoundError, Exception):
                continue

        return "\n\n".join(sections) if sections else "_No preference notes found._"
    except (FileNotFoundError, Exception):
        return "_No preference notes found._"

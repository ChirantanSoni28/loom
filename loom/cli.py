"""Typer CLI for Loom — setup wizard, config management, and hook commands."""

import asyncio
import json
import shutil
import subprocess
import sys

import typer
from rich import print as rprint
from rich.panel import Panel
from rich.prompt import Prompt

from loom.config import (
    LOOM_DIR,
    LoomConfig,
    LoomConfigNotFoundError,
    load_config,
    save_config,
    set_config_value,
)
from loom.db import init_db

app = typer.Typer(
    name="loom",
    help="Obsidian-backed graph retrieval memory for Claude Code.",
    no_args_is_help=True,
)

config_app = typer.Typer(help="View and update Loom settings.")
app.add_typer(config_app, name="config")

graph_app = typer.Typer(help="Manage the vault wikilink graph.")
app.add_typer(graph_app, name="graph")


# ---------------------------------------------------------------------------
# loom setup
# ---------------------------------------------------------------------------

def _check_ollama() -> str:
    """Check that Ollama is installed and return its version. Exit on failure."""
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        rprint(
            "[bold red]Error:[/] Ollama is not installed.\n"
            "Install it from: https://ollama.com/download\n"
            "Then run `loom setup` again."
        )
        raise typer.Exit(code=1)

    result = subprocess.run(
        ["ollama", "version"],
        capture_output=True,
        text=True,
    )
    version = result.stdout.strip() or "unknown"
    return version


def _pull_model(model: str) -> None:
    """Pull an embedding model via Ollama."""
    rprint(f"      Pulling {model}...")
    result = subprocess.run(
        ["ollama", "pull", model],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        rprint(f"[bold red]Error pulling model:[/] {result.stderr.strip()}")
        raise typer.Exit(code=1)
    rprint("      [green]Done[/green]")


def _create_vault_structure(vault_path: str) -> None:
    """Create the vault directory tree."""
    import pathlib

    base = pathlib.Path(vault_path)
    dirs = [
        base / "projects",
        base / "knowledge" / "patterns",
        base / "knowledge" / "preferences",
        base / "knowledge" / "tech",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def _prompt_api_key(label: str, required: bool = True) -> str:
    """Prompt user for an API key, hiding input."""
    while True:
        key = Prompt.ask(f"      {label}", password=True, default="" if not required else ...)
        if not required and not key:
            return ""
        if key:
            return key
        rprint("      [yellow]Key cannot be empty. Try again.[/yellow]")


@app.command()
def setup() -> None:
    """Interactive first-time setup wizard."""
    rprint(Panel("[bold]Loom Setup Wizard[/bold]", expand=False))
    rprint()

    # Step 1: Check Ollama
    rprint("[bold][1/7] Checking Ollama...[/bold]")
    version = _check_ollama()
    rprint(f"      [green]\u2713[/green] Ollama found ({version})")
    model = "nomic-embed-text"
    _pull_model(model)
    rprint()

    # Step 2: Create directory structure
    rprint("[bold][2/7] Creating ~/.loom/ directory structure...[/bold]")
    vault_path = LOOM_DIR / "vault"
    _create_vault_structure(str(vault_path))
    rprint(f"      [green]\u2713[/green] {vault_path}/projects/")
    rprint(f"      [green]\u2713[/green] {vault_path}/knowledge/")
    db_path = init_db()
    rprint(f"      [green]\u2713[/green] {db_path}  (schema initialized)")
    rprint()

    # Step 3: Obsidian CLI vault name
    rprint("[bold][3/7] Obsidian CLI[/bold]")
    rprint(
        "      Ensure the Obsidian CLI is enabled:\n"
        "      Settings > General > Advanced > Command line interface\n"
        "      Enter the vault name Loom should target."
    )
    vault_name = Prompt.ask("      Vault name", default="loom")
    rprint()

    # Step 4: Pinecone
    rprint("[bold][4/7] Pinecone[/bold]")
    pinecone_key = _prompt_api_key("API key")
    rprint()

    # Step 5: Anthropic API key (optional)
    rprint("[bold][5/7] Anthropic API key (optional — for compression feature)[/bold]")
    rprint("      Press Enter to skip (compression will remain disabled)")
    anthropic_key = _prompt_api_key("API key", required=False)
    rprint()

    # Step 6: Write config
    rprint("[bold][6/7] Writing ~/.loom/loom-settings.json...[/bold]")
    config = LoomConfig(
        vault_path=vault_path,
        obsidian_vault_name=vault_name,
        pinecone_api_key=pinecone_key,
        compression_enabled=bool(anthropic_key),
        compression_anthropic_key=anthropic_key or None,
    )
    save_config(config)
    rprint("      [green]\u2713[/green] Config saved")
    rprint()

    # Step 7: Done
    rprint("[bold][7/7] Done![/bold]")
    rprint("      Run `loom config show` to review settings.")
    rprint(f"      Next: open Obsidian pointed at {vault_path}")


# ---------------------------------------------------------------------------
# loom config show / set
# ---------------------------------------------------------------------------

@config_app.command("show")
def config_show() -> None:
    """Print current settings with API keys masked."""
    try:
        config = load_config()
    except LoomConfigNotFoundError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None

    masked = config.masked_display()
    rprint(json.dumps(masked, indent=2))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key (e.g. 'embedding_model')"),
    value: str = typer.Argument(help="New value"),
) -> None:
    """Update a single setting."""
    try:
        set_config_value(key, value)
    except LoomConfigNotFoundError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None
    except KeyError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None

    rprint(f"[green]\u2713[/green] Set [bold]{key}[/bold] = {value!r}")


# ---------------------------------------------------------------------------
# Hook commands: buffer-event, flush, context-hook
# ---------------------------------------------------------------------------


@app.command("buffer-event")
def buffer_event_cmd() -> None:
    """Buffer a tool event from stdin (PostToolUse hook).

    Reads JSON from stdin with keys: session_id, tool_name, tool_input,
    tool_response. Classifies and stores the event in SQLite.
    Always exits 0 to avoid blocking Claude Code.
    """
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise SystemExit(0)

        data = json.loads(raw)
        session_id = data.get("session_id", "")
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        tool_response = data.get("tool_response", {})

        if not session_id or not tool_name:
            raise SystemExit(0)

        from loom.capture.engine import CaptureEngine

        engine = CaptureEngine()
        engine.handle_post_tool_use(session_id, tool_name, tool_input, tool_response)
    except (json.JSONDecodeError, LoomConfigNotFoundError):
        pass
    except SystemExit:
        raise
    except Exception:
        # Never block Claude Code — swallow errors silently
        pass


@app.command("flush")
def flush_cmd(
    session_id: str = typer.Option(None, "--session-id", "-s", help="Session ID to flush (reads from stdin if not provided)"),
) -> None:
    """Flush buffered events into vault notes (Stop hook).

    Reads JSON from stdin with keys: session_id, cwd. Builds session
    notes and decision notes, writes them to the vault, and clears the buffer.
    """
    try:
        sid = session_id
        repo_path = ""

        if not sid:
            raw = sys.stdin.read()
            if raw.strip():
                data = json.loads(raw)
                sid = data.get("session_id", "")
                repo_path = data.get("cwd", "")

        if not sid:
            rprint("[bold red]Error:[/] No session_id provided.")
            raise typer.Exit(code=1)

        if not repo_path:
            # Fall back to current working directory
            import os
            repo_path = os.getcwd()

        from loom.capture.engine import CaptureEngine

        engine = CaptureEngine()
        result = asyncio.run(engine.handle_flush(sid, repo_path))

        if result["status"] == "empty":
            rprint("[yellow]No events buffered for this session.[/yellow]")
        else:
            rprint(f"[green]\u2713[/green] Session note: {result['session_note']}")
            for dec in result["decisions"]:
                rprint(f"[green]\u2713[/green] Decision: {dec}")

    except LoomConfigNotFoundError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None
    except json.JSONDecodeError:
        rprint("[bold red]Error:[/] Invalid JSON on stdin.")
        raise typer.Exit(code=1) from None


@app.command("context-hook")
def context_hook_cmd() -> None:
    """Load project context at session start (SessionStart hook).

    Reads JSON from stdin with keys: session_id, cwd. Prints project
    context markdown to stdout for injection into Claude's context window.
    """
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise SystemExit(0)

        data = json.loads(raw)
        repo_path = data.get("cwd", "")

        if not repo_path:
            raise SystemExit(0)

        from loom.server import loom_context

        context = asyncio.run(loom_context(repo_path))
        print(context)

    except (json.JSONDecodeError, LoomConfigNotFoundError):
        pass
    except SystemExit:
        raise
    except Exception:
        # Don't block session start
        pass


# ---------------------------------------------------------------------------
# Indexing commands: reindex
# ---------------------------------------------------------------------------


@app.command("reindex")
def reindex_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Re-index all notes regardless of content hash"),
    path: str = typer.Option(None, "--path", "-p", help="Re-index a single vault-relative path"),
) -> None:
    """Incrementally re-index vault notes into Pinecone.

    Scans ~/.loom/vault/ for changed files (by content hash), generates
    embeddings via Ollama, and upserts vectors to Pinecone.
    """
    try:
        config = load_config()
    except LoomConfigNotFoundError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None

    from loom.retrieval.indexer import reindex_vault

    rprint("[bold]Scanning vault...[/bold]")

    try:
        report = asyncio.run(reindex_vault(config, force=force, single_path=path))
    except Exception as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None

    rprint(f"  {report.total_notes} notes found")
    rprint(f"  {report.new_notes} new, {report.changed_notes} changed, {report.unchanged_notes} unchanged")
    rprint(f"Embedded {report.total_chunks} chunks")
    rprint(f"Upserted to Pinecone: {report.vectors_upserted} vectors")
    rprint(f"Deleted {report.deleted_notes} stale notes")
    rprint("[green]Done.[/green]")


# ---------------------------------------------------------------------------
# Graph commands: graph rebuild, graph neighbors, graph stats
# ---------------------------------------------------------------------------


@graph_app.command("rebuild")
def graph_rebuild_cmd() -> None:
    """Rebuild the wikilink graph from vault notes."""
    try:
        config = load_config()
    except LoomConfigNotFoundError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None

    from pathlib import Path

    from loom.db import get_connection
    from loom.retrieval.graph import VaultGraph

    db = get_connection()
    graph = VaultGraph(db)

    rprint("[bold]Rebuilding graph...[/bold]")
    edge_count = asyncio.run(graph.rebuild(Path(config.vault_path)))
    stats = graph.stats()
    db.close()

    rprint(f"  {stats['nodes']} nodes, {edge_count} edges")
    rprint("[green]Done.[/green]")


@graph_app.command("neighbors")
def graph_neighbors_cmd(
    path: str = typer.Argument(help="Vault-relative path of the note"),
) -> None:
    """Show direct neighbors of a note."""
    from loom.db import get_connection
    from loom.retrieval.graph import VaultGraph

    db = get_connection()
    graph = VaultGraph(db)
    nbrs = graph.neighbors(path, direction="both")
    db.close()

    if not nbrs:
        rprint("[yellow]No neighbors found.[/yellow]")
    else:
        for n in nbrs:
            rprint(f"  - {n}")


@graph_app.command("stats")
def graph_stats_cmd() -> None:
    """Print graph node and edge counts."""
    from loom.db import get_connection
    from loom.retrieval.graph import VaultGraph

    db = get_connection()
    graph = VaultGraph(db)
    stats = graph.stats()
    db.close()

    rprint(f"Nodes: {stats['nodes']}")
    rprint(f"Edges: {stats['edges']}")


# ---------------------------------------------------------------------------
# Compression commands
# ---------------------------------------------------------------------------


@app.command("compress")
def compress_cmd(
    project: str = typer.Option(..., "--project", "-p", help="Project name to compress"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be compressed without doing it"),
    all_projects: bool = typer.Option(False, "--all", help="Compress all projects"),
) -> None:
    """Run compression for a project's session notes."""
    try:
        config = load_config()
    except LoomConfigNotFoundError as e:
        rprint(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None

    if not config.compression_enabled:
        rprint("[yellow]Compression is disabled.[/yellow]")
        rprint("Enable it: loom config set compression_enabled true")
        raise typer.Exit(code=0)

    from loom.compression.scheduler import check_compression, run_hot_to_warm, run_warm_to_cold

    async def _run() -> None:
        async with VaultClient(config) as client:
            report = await check_compression(project, config, client)

            if dry_run:
                rprint(f"[bold]Compression report for {project}:[/bold]")
                rprint(f"  Hot sessions ready: {len(report.hot_ready)}")
                rprint(f"  Warm rollups ready: {len(report.warm_ready)}")
                return

            if report.hot_ready:
                rprint(f"Compressing {len(report.hot_ready)} hot sessions...")
                warm_path = await run_hot_to_warm(project, report.hot_ready, config, client)
                rprint(f"[green]\u2713[/green] Warm rollup: {warm_path}")

            if report.warm_ready:
                rprint(f"Compressing {len(report.warm_ready)} warm rollups...")
                cold_path = await run_warm_to_cold(project, report.warm_ready, config, client)
                rprint(f"[green]\u2713[/green] Cold digest: {cold_path}")

            if not report.hot_ready and not report.warm_ready:
                rprint("[yellow]Nothing to compress.[/yellow]")

    from loom.vault import VaultClient
    asyncio.run(_run())

"""Typer CLI for Loom — setup wizard, config management, and future commands."""

import json
import shutil
import subprocess

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

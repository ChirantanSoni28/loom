# Loom

Obsidian-backed graph retrieval memory for Claude Code.

## Installation

```bash
pip install loom-claude
loom setup
```

## Usage

```bash
loom --help
```

## Packages

This repo contains two packages:

### `loom-claude` (root)

The main Loom plugin — captures Claude Code sessions, stores knowledge in an Obsidian vault, and retrieves context via hybrid vector + graph search.

### `obsidian-mcp` (obsidian-mcp/)

A standalone MCP server for Obsidian via the Obsidian CLI. Usable independently by any MCP-compatible agent — no Loom dependency required. Loom imports `ObsidianCLI` directly as a Python library to avoid MCP protocol overhead for in-process calls.

```bash
# Run as MCP server
obsidian-mcp

# Or use as a library
from obsidian_mcp import ObsidianCLI
```

See [obsidian-mcp/README.md](obsidian-mcp/README.md) for details.

## License

MIT

"""Obsidian MCP — MCP server for Obsidian via the Obsidian CLI."""

__version__ = "0.1.0"

from obsidian_mcp.cli import ObsidianCLI, ObsidianCLIError, ObsidianCLINotFoundError, SearchResult

__all__ = ["ObsidianCLI", "ObsidianCLIError", "ObsidianCLINotFoundError", "SearchResult"]

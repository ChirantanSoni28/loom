"""Entry point for `python -m loom` — starts the MCP server via stdio."""

import asyncio

from loom.server import server


def main() -> None:
    """Run the Loom MCP server over stdio transport."""
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()

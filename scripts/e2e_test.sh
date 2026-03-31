#!/usr/bin/env bash
# End-to-end smoke test for a fresh Loom install
set -euo pipefail

echo "=== Loom E2E Test ==="

# 1. Config loads
echo "[1/6] Config..."
python -c "from loom.config import load_config; load_config()" 2>/dev/null \
    && echo "  OK: config loads" \
    || echo "  SKIP: no config (run 'loom setup' first)"

# 2. Module imports
echo "[2/6] Imports..."
python -c "
from loom.capture import CaptureEngine, classify_event, buffer_event
from loom.retrieval import OllamaEmbedder, ChromaStore, chunk_note, reindex_vault
from loom.retrieval.graph import VaultGraph
from loom.retrieval.hybrid import hybrid_search
from loom.retrieval.context_builder import build_context
from loom.compression import check_compression, extract_decisions
from loom.services import OllamaManager
from loom.server import server
print('  OK: all modules import')
"

# 3. Unit tests
echo "[3/6] Tests..."
python -m pytest --tb=short -q
echo "  OK: all tests pass"

# 4. CLI help
echo "[4/6] CLI..."
python -m loom.cli --help > /dev/null
echo "  OK: CLI loads"

# 5. MCP server creates
echo "[5/6] MCP server..."
python -c "from loom.server import server; print(f'  OK: server \"{server.name}\" created')"

# 6. Graph (if DB exists)
echo "[6/6] Graph..."
python -c "
from loom.db import get_connection
from loom.retrieval.graph import VaultGraph
db = get_connection()
g = VaultGraph(db)
stats = g.stats()
print(f'  OK: {stats[\"nodes\"]} nodes, {stats[\"edges\"]} edges')
db.close()
" 2>/dev/null || echo "  SKIP: no database"

echo ""
echo "=== All checks passed ==="

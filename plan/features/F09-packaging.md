# F09: Plugin Packaging + Open Source Release

**Status:** pending
**Depends on:** F01–F08 complete and reviewed
**Review gate:** `claude plugin install chirantansoni/loom` on a fresh machine completes successfully; full session capture + retrieval works end-to-end

---

## Goal

Package Loom as a proper Claude Code plugin, publish to PyPI, and prepare the open-source release. After this feature, anyone can install Loom with a single command. The repo is clean, documented, and ready for community contributions.

---

## Deliverables

### 1. Claude Code Plugin Manifest (`.claude-plugin/plugin.json`)

```json
{
  "name": "loom",
  "version": "0.1.0",
  "description": "Obsidian-backed graph retrieval memory for Claude Code. Automatically captures sessions and retrieves relevant context using hybrid semantic + graph search.",
  "author": "chirantansoni",
  "license": "MIT",
  "homepage": "https://github.com/chirantansoni/loom",
  "requirements": {
    "ollama": ">=0.3.0",
    "python": ">=3.12"
  },
  "post_install": "scripts/install.sh"
}
```

### 2. `scripts/install.sh` (post-install hook)

```bash
#!/bin/bash
set -e

echo "Loom: Running setup wizard..."
python -m loom setup

echo ""
echo "✓ Loom installed successfully."
echo "  Open Obsidian and point it to ~/.loom/vault/"
echo "  Then start a new Claude Code session — Loom will capture automatically."
```

### 3. `.claude-plugin/.mcp.json` (final)

```json
{
  "mcpServers": {
    "loom": {
      "command": "python",
      "args": ["-m", "loom"],
      "env": {}
    }
  }
}
```

### 4. `.claude-plugin/settings.json` (final hooks)

```json
{
  "hooks": {
    "SessionStart": [{
      "type": "command",
      "command": "python -m loom context-hook",
      "timeout": 10000
    }],
    "PostToolUse": [{
      "type": "command",
      "command": "python -m loom buffer-event",
      "timeout": 2000
    }],
    "Stop": [{
      "type": "command",
      "command": "python -m loom flush",
      "timeout": 30000
    }]
  }
}
```

---

### 5. `pyproject.toml` (final)

```toml
[project]
name = "loom-claude"
version = "0.1.0"
description = "Obsidian-backed graph retrieval memory for Claude Code"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.12"
keywords = ["claude", "mcp", "obsidian", "memory", "rag"]

dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "mcp>=1.0",
    "pinecone>=5.0",
    "anthropic>=0.40",
    "rich>=13.0",
]

[project.scripts]
loom = "loom.cli:app"

[project.urls]
Homepage = "https://github.com/chirantansoni/loom"
Issues = "https://github.com/chirantansoni/loom/issues"
```

---

### 6. README.md

Sections:
1. **What is Loom** — one paragraph + architecture diagram
2. **Prerequisites** — Ollama, Obsidian + local-rest-api plugin, Pinecone account
3. **Installation** — `claude plugin install chirantansoni/loom` + `loom setup`
4. **How it works** — session capture → vault → hybrid retrieval
5. **Configuration** — `loom-settings.json` reference
6. **Multi-machine** — Obsidian Sync setup
7. **Compression** — how to enable + configure
8. **Changing embedding model** — `loom reindex` workflow
9. **Contributing** — feature branch workflow, feature file format
10. **License** — MIT

---

### 7. End-to-End Test Script (`scripts/e2e_test.sh`)

```bash
#!/bin/bash
# End-to-end smoke test for a fresh Loom install

set -e

echo "=== Loom E2E Test ==="

# 1. Config loads
python -m loom config show

# 2. Vault write + read
python -m loom debug write-note "test/smoke.md" "# Smoke test\nThis is a test note."
python -m loom debug read-note "test/smoke.md"

# 3. Index
python -m loom reindex --path "test/smoke.md"

# 4. Search returns result
python -m loom debug search "smoke test"

# 5. Graph
python -m loom graph rebuild
python -m loom graph stats

# 6. MCP server starts
timeout 3 python -m loom || true

echo "=== All checks passed ==="
```

---

## Release Checklist

- [ ] All F01–F08 acceptance criteria met
- [ ] `scripts/e2e_test.sh` passes on fresh machine
- [ ] `claude plugin install chirantansoni/loom` works (tested on fresh machine)
- [ ] `loom setup` wizard works end-to-end
- [ ] README covers all user-facing configuration
- [ ] `pyproject.toml` published to PyPI as `loom-claude`
- [ ] GitHub repo is public with MIT license
- [ ] GitHub Actions CI runs `e2e_test.sh` on push
- [ ] CONTRIBUTING.md describes feature development workflow (feature file → implement → review gate)

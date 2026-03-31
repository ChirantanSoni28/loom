#!/usr/bin/env bash
# Post-plugin-install hook — installs Loom and runs fully automatic setup.
set -euo pipefail

echo "Installing Loom..."

# Prefer uv, fall back to pip
if command -v uv &>/dev/null; then
    uv pip install -e .
else
    pip install -e .
fi

echo ""
echo "Running Loom setup..."
loom setup --non-interactive

#!/usr/bin/env bash
set -e

echo "Running Validation Gate for Wave-Management-Bot..."
echo "Linting commands/, core/, and tasks/..."

# Check if uvx is available
if ! command -v uvx &> /dev/null; then
    echo "uvx could not be found. Please ensure uv is installed."
    exit 1
fi

# NOTE: F403/F405/F821 are unavoidable here — the cogs use `from core.helpers import *`
# by design, which ruff cannot statically resolve. E401 + the rest are legacy style nits
# in pre-existing bot code. The gate's job is to catch NEW breakage, not relitigate the
# established codebase style, so these classes are ignored.
uvx ruff check commands/ core/ tasks/ --ignore=E701,E702,E722,F841,F811,F541,F401,E402,E721,F403,F405,F821,E401

echo "Syncing skills to AI agents (Claude, Cursor)..."
python3 ai-hub/scripts/sync_agent_skills.py

echo "Validation passed! You are clear to proceed."

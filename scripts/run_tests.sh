#!/usr/bin/env bash
# Run the full codeKG test suite locally (no Docker, no live Neo4j required).
#
# Usage:
#   ./scripts/run_tests.sh            # run all tests
#   ./scripts/run_tests.sh -k impact  # run matching subset
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv-test"

# ── Create / reuse venv ────────────────────────────────────────────────────

if [ ! -f "$VENV/bin/python" ]; then
  echo "→ Creating test venv at $VENV"
  python3 -m venv "$VENV"
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# ── Install deps ───────────────────────────────────────────────────────────

echo "→ Installing test dependencies"
"$PIP" install -q \
  pytest>=8.0 pytest-asyncio>=0.23 httpx \
  "fastapi>=0.111.0,<0.116.0" "starlette>=0.37.0,<0.47.0" \
  "neo4j>=5.20.0" "pydantic>=2.7.2" "pydantic-settings>=2.3.4" "jinja2>=3.1.4" \
  "gitpython>=3.1.43" "python-multipart>=0.0.9" \
  "markdown>=3.6" "anthropic>=0.25.0" "openai>=1.30.0" \
  "docker>=7.0.0" "itsdangerous>=2.1.2" \
  "tree-sitter>=0.22.3" "tree-sitter-java>=0.21.0" \
  "tree-sitter-python>=0.23.0" "tree-sitter-cpp>=0.23.0" \
  "mcp>=1.3.0"

# ── Run tests ─────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Running API unit tests"
echo "═══════════════════════════════════════════════════════"
PYTHONPATH="$ROOT/services/api:$ROOT:${PYTHONPATH:-}" \
"$VENV/bin/pytest" \
  "$ROOT/services/api/tests/" \
  -v --tb=short "$@"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Running Console tests"
echo "═══════════════════════════════════════════════════════"
# Console's PYTHONPATH must list services/console BEFORE services/api so
# 'import main' resolves to the console main, not the API main.
PYTHONPATH="$ROOT/services/console:$ROOT/services/api:$ROOT:${PYTHONPATH:-}" \
"$VENV/bin/pytest" \
  "$ROOT/services/console/tests/" \
  -v --tb=short "$@"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Running Ingestion tests"
echo "═══════════════════════════════════════════════════════"
PYTHONPATH="$ROOT/services/ingestion:$ROOT:${PYTHONPATH:-}" \
"$VENV/bin/pytest" \
  "$ROOT/services/ingestion/tests/" \
  -v --tb=short "$@"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Running MCP tests"
echo "═══════════════════════════════════════════════════════"
PYTHONPATH="$ROOT/services/mcp:$ROOT:${PYTHONPATH:-}" \
"$VENV/bin/pytest" \
  "$ROOT/services/mcp/tests/" \
  -v --tb=short "$@"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Running Watcher tests"
echo "═══════════════════════════════════════════════════════"
PYTHONPATH="$ROOT/services/watcher:$ROOT:${PYTHONPATH:-}" \
"$VENV/bin/pytest" \
  "$ROOT/services/watcher/tests/" \
  -v --tb=short "$@"

echo ""
echo "✓ All tests passed"

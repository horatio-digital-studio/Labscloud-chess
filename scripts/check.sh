#!/usr/bin/env bash
# All fast gates. Run with: uv run ./scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff lint";        ruff check .
echo "== ruff format";      ruff format --check .
echo "== pyright";          pyright
echo "== unit + contract";  python -m pytest tests/unit tests/contract --cov --cov-report=term --cov-fail-under=95
echo "== JS unit tests";    node --test --test-reporter=dot tests/js/*.test.mjs
echo "== traceability";     python scripts/check_traceability.py
echo "All fast gates passed."

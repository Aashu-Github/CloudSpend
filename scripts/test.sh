#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
if command -v ruff >/dev/null 2>&1; then
  ruff check cloudspend tests app.py
fi
PYTHONPATH=. python -m pytest -q

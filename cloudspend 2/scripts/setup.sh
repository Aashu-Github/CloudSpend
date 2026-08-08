#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "CloudSpend requires Python 3.11+." >&2
  exit 1
fi
"$PYTHON_BIN" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
[[ -f .env ]] || cp .env.example .env
mkdir -p data
printf '\nSetup complete. Next:\n  ./scripts/run.sh --demo\n  ./scripts/run_pages.sh   # optional GitHub Pages frontend preview\n  ./scripts/test.sh\n'

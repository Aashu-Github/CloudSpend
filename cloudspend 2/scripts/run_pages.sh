#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Static CloudSpend frontend: http://127.0.0.1:8000"
echo "It expects the Flask API at http://127.0.0.1:8080 when run locally."
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs

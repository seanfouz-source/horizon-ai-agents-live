#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Local Python environment not found. Run:"
  echo "python3.12 -m venv .venv"
  echo ".venv/bin/python -m pip install -e '.[dev]'"
  exit 1
fi

PORT="${PORT:-8010}"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"

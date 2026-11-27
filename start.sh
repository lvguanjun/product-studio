#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"
exec uv run uvicorn app:app --host "$HOST" --port "$PORT"

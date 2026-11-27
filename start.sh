#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
HOST="${HOST:-0.0.0.0}"
exec uv run uvicorn app:app --host "$HOST" --port "$PORT"

#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
export BOT_HOST="${BOT_HOST:-127.0.0.1}"
export BOT_PORT="${BOT_PORT:-8000}"
if [[ "$BOT_HOST" != 127.0.0.1 && "$BOT_HOST" != localhost && "$BOT_HOST" != ::1 ]]; then
  echo 'BOT_HOST debe ser local; use un tunel SSH para acceso remoto.' >&2
  exit 1
fi
install -d -m 700 "${BOT_DATA_DIR:-./data}"
exec flock -n "${BOT_DATA_DIR:-./data}/instance.lock" .venv/bin/python -m uvicorn webapp.api:app --host "$BOT_HOST" --port "$BOT_PORT" --workers 1

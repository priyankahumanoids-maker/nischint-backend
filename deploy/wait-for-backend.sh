#!/bin/bash
# wait-for-backend.sh
#
# Blocks until the FastAPI backend on :8001 is accepting requests AND
# returning 200 on /api/health, up to MAX_WAIT_SECONDS.
#
# Call this right after `supervisorctl restart backend` (or in any deploy
# pipeline) BEFORE reloading nginx so nginx never routes to a port that
# isn't listening yet — root cause of intermittent "Connection refused".
#
# Usage:
#   /app/deploy/wait-for-backend.sh                  # default: 60s timeout
#   MAX_WAIT_SECONDS=30 /app/deploy/wait-for-backend.sh
#
# Exit codes:
#   0  — backend is up and /api/health returned 200
#   1  — timed out
#   2  — uvicorn process not running at all

set -u

HOST="${BACKEND_HOST:-127.0.0.1}"
PORT="${BACKEND_PORT:-8001}"
PATH_HEALTH="${HEALTH_PATH:-/api/health}"
MAX_WAIT="${MAX_WAIT_SECONDS:-60}"
INTERVAL="${POLL_INTERVAL_SECONDS:-1}"

echo "[wait-for-backend] target=http://${HOST}:${PORT}${PATH_HEALTH}  timeout=${MAX_WAIT}s"

# 1. Sanity-check that a uvicorn process exists (fast-fail)
if ! pgrep -f "uvicorn.*server:app" >/dev/null 2>&1; then
  echo "[wait-for-backend] ✗ uvicorn process not found — is supervisor running?"
  exit 2
fi

# 2. Poll TCP + HTTP health
start_ts=$(date +%s)
while :; do
  elapsed=$(( $(date +%s) - start_ts ))
  if [ "$elapsed" -ge "$MAX_WAIT" ]; then
    echo "[wait-for-backend] ✗ timed out after ${MAX_WAIT}s"
    exit 1
  fi

  # TCP bind check (fast)
  if ! (echo > /dev/tcp/${HOST}/${PORT}) 2>/dev/null; then
    printf "."
    sleep "$INTERVAL"
    continue
  fi

  # HTTP 200 check
  code=$(curl -s -o /dev/null -w '%{http_code}' \
         --max-time 3 "http://${HOST}:${PORT}${PATH_HEALTH}" || echo 000)
  if [ "$code" = "200" ]; then
    echo ""
    echo "[wait-for-backend] ✓ ready after ${elapsed}s (HTTP ${code})"
    exit 0
  fi

  printf "."
  sleep "$INTERVAL"
done

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/dev.sh — start the backend and frontend together, and stop BOTH cleanly.
# READING ORDER: 5
#
# WHY this script exists:
#   Running two long-lived servers by hand means two terminals and remembering to
#   kill both. This starts them as background jobs, then installs a `trap` so that
#   when you press Ctrl-C (SIGINT) — or the script exits for any reason — we kill
#   the whole process group. Without the trap, killing this script would orphan
#   the uvicorn and vite processes, and the next `make dev` would fail on a busy port.
# ─────────────────────────────────────────────────────────────────────────────

# set -e: exit on any command failure. set -u: error on unset variables.
# These two catch bugs early instead of letting the script limp along silently.
set -euo pipefail

# Resolve the repo root from this script's own location, so `make dev` works no
# matter what directory you invoke it from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# cleanup() runs on EXIT (normal or via Ctrl-C). `kill 0` signals every process
# in this script's process group — i.e. both servers we started below.
cleanup() {
  echo ""
  echo "[dev.sh] shutting down backend + frontend..."
  # Ignore errors here: a process may already be gone.
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[dev.sh] starting backend on http://127.0.0.1:8000 ..."
(
  cd "$ROOT_DIR/backend"
  uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &

echo "[dev.sh] starting frontend on http://127.0.0.1:5173 ..."
(
  cd "$ROOT_DIR/frontend"
  npm run dev
) &

echo "[dev.sh] both running. Open http://localhost:5173  (Ctrl-C stops both)."

# `wait` blocks here until the background jobs exit (or Ctrl-C fires the trap).
wait

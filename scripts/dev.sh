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

# Fail before starting either half of the app. Previously a missing `uv` let Vite
# keep running by itself, which looked like a broken UI even though the backend had
# exited immediately.
if ! command -v uv >/dev/null 2>&1; then
  echo "[dev.sh] ERROR: uv is not installed or not on PATH."
  echo "[dev.sh] Install it from https://docs.astral.sh/uv/ and run 'make install'."
  exit 127
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "[dev.sh] ERROR: npm is not installed or not on PATH. Install Node 20+."
  exit 127
fi
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "[dev.sh] ERROR: frontend dependencies are missing. Run 'make install' first."
  exit 1
fi

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
backend_pid=$!

echo "[dev.sh] starting frontend on http://127.0.0.1:5173 ..."
(
  cd "$ROOT_DIR/frontend"
  npm run dev
) &
frontend_pid=$!

echo "[dev.sh] both running. Open http://localhost:5173  (Ctrl-C stops both)."

# Stop the combined launcher as soon as either server dies. A half-running app is
# misleading and cannot be healthy, so the EXIT trap then cleans up the survivor.
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
  echo "[dev.sh] ERROR: backend exited; shutting down the frontend."
else
  echo "[dev.sh] ERROR: frontend exited; shutting down the backend."
fi
exit 1

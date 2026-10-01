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
  echo "[dev.sh] ERROR: npm is not installed or not on PATH. Install Node 20.19+ or 22.12+."
  exit 127
fi
node_ok="$(node -p 'const [major, minor] = process.versions.node.split(".").map(Number); Number((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)' 2>/dev/null || true)"
if [[ "$node_ok" != "1" ]]; then
  echo "[dev.sh] ERROR: Vite requires Node 20.19+ or 22.12+."
  exit 1
fi
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "[dev.sh] ERROR: frontend dependencies are missing. Run 'make install' first."
  exit 1
fi

# Refuse to create a half-running stack when another process already owns one of
# the fixed development ports. In addition to being clearer than Uvicorn's errno,
# this avoids briefly starting Vite only to tear it down again.
require_free_port() {
  local label="$1"
  local port="$2"
  local listeners=""

  if command -v lsof >/dev/null 2>&1; then
    if listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null)"; then
      echo "[dev.sh] ERROR: $label port $port is already in use."
      echo "$listeners"
      echo "[dev.sh] Stop the listed process, confirm the port is free, then retry."
      echo "[dev.sh] Inspect again with: lsof -nP -iTCP:$port -sTCP:LISTEN"
      exit 1
    fi
  fi
}

require_free_port "backend" 8000
require_free_port "frontend" 5173

backend_pid=""
frontend_pid=""

# Each background server gets its own process group. Cleanup signals only those
# groups, never this script's parent shell or `make`. The EXIT trap removes all
# signal traps before sending anything, so cleanup cannot recursively invoke itself.
signal_server_group() {
  local signal_name="$1"
  local pid="$2"
  [[ -n "$pid" ]] || return 0
  kill -"$signal_name" -- "-$pid" 2>/dev/null || kill -"$signal_name" "$pid" 2>/dev/null || true
}

server_group_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 -- "-$pid" 2>/dev/null
}

cleanup() {
  trap - EXIT INT TERM
  if [[ -z "$backend_pid" && -z "$frontend_pid" ]]; then
    return
  fi

  echo ""
  echo "[dev.sh] shutting down backend + frontend..."
  signal_server_group TERM "$backend_pid"
  signal_server_group TERM "$frontend_pid"

  # Give Uvicorn/Vite a short graceful-shutdown window, then reap any stubborn
  # descendants in the two isolated groups so the next launch has clean ports.
  for _attempt in {1..20}; do
    if ! server_group_alive "$backend_pid" && ! server_group_alive "$frontend_pid"; then
      break
    fi
    sleep 0.1
  done
  server_group_alive "$backend_pid" && signal_server_group KILL "$backend_pid"
  server_group_alive "$frontend_pid" && signal_server_group KILL "$frontend_pid"
  wait "$backend_pid" 2>/dev/null || true
  wait "$frontend_pid" 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[dev.sh] starting backend on http://127.0.0.1:8000 ..."
# Job control gives each background subshell a process group whose id is its pid.
# That lets cleanup stop Uvicorn's reloader children without signaling `make` or zsh.
set -m
(
  cd "$ROOT_DIR/backend"
  exec uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
backend_pid=$!

echo "[dev.sh] starting frontend on http://127.0.0.1:5173 ..."
(
  cd "$ROOT_DIR/frontend"
  exec npm run dev
) &
frontend_pid=$!
set +m

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

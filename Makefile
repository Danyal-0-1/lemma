# ─────────────────────────────────────────────────────────────────────────────
# Makefile — the four commands you actually run while developing.
# READING ORDER: 4
#
# WHY a Makefile: it gives every task ONE canonical name, so you never have to
# remember the exact uv / npm incantation. `make dev` is the command you'll use
# most — it starts the backend and frontend together.
#
# Note: Make targets that are not real files must be declared .PHONY, otherwise
# a file named "dev" in this folder would make `make dev` do nothing.
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help install backend frontend dev test lint

# Running `make` with no target prints this help (the first target is the default,
# but we make `help` explicit for clarity).
help:
	@echo "AI Company — available commands:"
	@echo "  make install   Install backend (uv) and frontend (npm) dependencies"
	@echo "  make backend   Run the FastAPI backend on 127.0.0.1:8000"
	@echo "  make frontend  Run the Vite dev server on 127.0.0.1:5173"
	@echo "  make dev       Run BOTH together (this is the one you want)"
	@echo "  make test      Run backend pytest + frontend typecheck/build"
	@echo "  make lint      Run ruff (backend) + tsc (frontend)"

# --- Dependency installation ------------------------------------------------
# uv sync reads backend/pyproject.toml and creates a locked virtualenv.
# npm install reads frontend/package.json.
install:
	cd backend && uv sync
	cd frontend && npm install

# --- Individual servers -----------------------------------------------------
# These are handy when you want just one process in the foreground to read its logs.
backend:
	cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

# --- Both at once -----------------------------------------------------------
# Delegates to scripts/dev.sh, which starts both and kills both on Ctrl-C.
dev:
	./scripts/dev.sh

# --- Quality gates ----------------------------------------------------------
test:
	cd backend && uv run pytest
	cd frontend && npm run build

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run typecheck

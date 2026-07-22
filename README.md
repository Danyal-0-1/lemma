<!-- READING ORDER: 1 — start here. -->
# AI Company

A **local-first, single-user** web app for turning a rough idea into a build-ready
spec with a small crew of AI roles, then handing that spec to a real coding agent
(Claude Code / Codex) that you drive in an embedded terminal — with live diffs,
checks, and a built-in mentor that explains any code to you.

It looks like VS Code and works like [Conductor](https://conductor.build): three
panels, a diff-first review loop, and chrome that only shows what the current moment
needs. It is **not** an IDE — your real editor and the coding agent write the code;
this app orchestrates and reviews.

> **This is a learning codebase.** Every file is heavily commented and ranked with a
> `READING ORDER`. See [`LEARNING_PATH.md`](LEARNING_PATH.md) for the reading/retyping
> plan and [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces fit.

---

## Status

Built milestone by milestone (see [`PROMPT.md`](PROMPT.md) §14). Current progress lives
in [`CLAUDE.md`](CLAUDE.md) under *Milestone status*, and in `git log --oneline`.

- **M0 — Scaffold** ✅ repo layout, dev tooling, empty FastAPI `/health`, dark UI shell.
- M1–M8: in progress / upcoming.

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.12+ | backend |
| [uv](https://docs.astral.sh/uv/) | latest | fast Python package/venv manager |
| Node | 20+ | frontend (Vite) |
| git | any recent | version control + workspace diffs |

Install `uv` (if you don't have it):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Setup & run (Linux & macOS)

```bash
# 1. Install dependencies (backend venv via uv, frontend via npm)
make install

# 2. Create your local env file. The defaults run in MOCK mode — zero keys, zero cost.
cp backend/.env.example backend/.env

# 3. Start both servers (backend :8000, frontend :5173)
make dev
```

Then open **http://localhost:5173**.

> **First run is free.** `MOCK_LLM=true` (the default) streams believable canned crew
> responses, so you can explore the entire app without any API keys or spend.

---

## Using real models (optional)

1. Get a [DeepSeek](https://platform.deepseek.com/) API key (cheapest; the crew's default).
2. Put it in `backend/.env`:
   ```bash
   DEEPSEEK_API_KEY=sk-...
   MOCK_LLM=false
   ```
3. Restart `make dev`. The cost meter in the status bar now tracks real spend.

### ⚠️ The billing warning (read this once)

**Never `export ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) in the shell where you run
Claude Code or this app.** If that variable is set, the `claude` CLI bills your
**API account per token** instead of using your **subscription**. This app:

- keeps its keys in `backend/.env` (loaded into the backend process only), and
- **strips** `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from the environment before it
  spawns the embedded terminal — so a `claude` session you start there uses your
  subscription, not metered API billing.

This is enforced in `backend/app/terminal/pty_service.py` (arriving in M5).

---

## Why it binds to 127.0.0.1 only

This app spawns shells and runs commands inside your project workspaces. Binding to
`0.0.0.0` would expose that to your whole network. It therefore refuses to start on any
other host unless you explicitly set `I_UNDERSTAND_THE_RISK=true`.

---

## Troubleshooting

- **Port already in use** — a previous `make dev` didn't shut down. Find and kill it:
  `lsof -i :8000` / `lsof -i :5173`, then `kill <pid>`.
- **PTY issues on macOS** (M5+) — covered here once the terminal ships.
- **WebSocket won't connect** — check that the backend is up (`curl http://127.0.0.1:8000/health`)
  and that no proxy/VPN is blocking `ws://localhost`.

---

## Layout

See [`PROMPT.md`](PROMPT.md) §5 for the full tree, or [`ARCHITECTURE.md`](ARCHITECTURE.md)
for the runtime picture. Top level: `backend/` (FastAPI), `frontend/` (Vite + React),
`learning/` (your retyping scratch space), `scripts/` (dev helpers).

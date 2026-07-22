# CLAUDE.md — conventions, decisions, and how to resume

<!-- READING ORDER: 2 — read after README.md. -->

This file is the project's memory for any AI (or human) picking up the build cold.
It records **how** we write code here, **why** key decisions were made, and **where**
we are. Keep it current — it is the contract every future session inherits.

> The full specification is [`PROMPT.md`](PROMPT.md). If anything here conflicts with
> PROMPT.md, **PROMPT.md wins** — and the conflict should be flagged, not silently resolved.

---

## How to resume a build session

1. Read [`PROMPT.md`](PROMPT.md) (the spec) and this file.
2. Run `git log --oneline` to see which milestones are committed.
3. Continue from the next unfinished milestone in PROMPT.md §14. One milestone at a
   time: implement → run its acceptance checks → commit with a conventional message →
   summarize → (per the user's request) **pause for go-ahead** before the next.

---

## Milestone status

| Milestone | State | Commit |
|---|---|---|
| M0 — Scaffold | ✅ done | see `git log` |
| M1 — Event pipe + fake events | ✅ done | see `git log` |
| M2 — ModelProvider + one real role | ⏳ next | — |
| M3 — Full crew + approval gate + Spec | ▫ todo | — |
| M4 — Spec tab + history + export | ▫ todo | — |
| M5 — Workspaces + Terminal | ▫ todo | — |
| M6 — Diff + Files + Checks | ▫ todo | — |
| M7 — Explain (mentor) | ▫ todo | — |
| M8 — Polish + learning pass | ▫ todo | — |
| M9 — Headless AgentProvider | ▫ optional | — |

---

## Conventions (follow these in every file)

**The prime directive:** someone will retype this code to learn programming. Clarity
outranks cleverness, brevity, and micro-performance. Concretely (PROMPT.md §1):

- Every file opens with a header comment: *what it does*, *how it fits*, and a
  `READING ORDER: n` rank.
- Docstrings on every public function/class: one line of *what*, then *why it exists*.
- Inline comments explain **why**, never the obvious *what*.
- No clever one-liners. Prefer 5 clear lines over 1 dense one.
- Target ≤ 250 lines per file; split before exceeding.
- Python: full type hints, pydantic v2 for boundary data. TypeScript: `strict: true`.
- Consistent patterns: once a route/event/store shape is set, every sibling matches it.

**Backend**

- FastAPI + Python 3.12, managed with `uv` (`backend/pyproject.toml`).
- `logging` module loggers only — **no `print()`**.
- Bind `127.0.0.1` only (it executes shell commands).
- Tests with `pytest`; lint with `ruff`. Both clean at every commit.

**Frontend**

- Vite + React 18 + TypeScript strict; state via `zustand`.
- Tailwind mapped to VS Code Dark+ CSS variables defined in `src/theme.css`.
- WebSocket/PTY hooks use `useEffect` **with cleanup** so React 18 Strict Mode's
  double-mount never leaves ghost connections.

**Git**

- Conventional commits, one per milestone minimum: `feat(M1): websocket event bus + shell`.
- Never commit `.env`, `backend/data/`, or workspace directories (see `.gitignore`).

---

## Decisions (append as we go — the "why" behind non-obvious choices)

- **No agent framework (CrewAI/LangGraph/AutoGen).** The ideation loop is a ~4-step
  sequential state machine with one human gate. A framework would hide exactly the
  mechanics this codebase exists to teach. Revisit only if real branching is needed.
- **`uv` for the backend** (PROMPT.md §4). Installed via the Astral standalone
  installer; it lives at `~/.local/bin/uv`.
- **Project root is `ai-company/`** — a subfolder of the working directory, matching
  the spec's example layout. `PROMPT.md` is copied in verbatim and never modified.
- **Tailwind v3** (classic `tailwind.config.js` + PostCSS). Chosen over v4's CSS-first
  `@theme` because the explicit config file makes the mapping from Dark+ tokens →
  utility classes visible and teachable — better for a learner retyping it.
- **Mock mode (`MOCK_LLM=true`) is the default and a first-class feature**, not a stub.
  The whole app is demoable with zero keys and zero cost.
- **`seq` is per-connection, assigned at send time** by `Sequencer` in `events.py`, not
  at publish time — because two browsers each get their own 1,2,3… stream. The client
  (`ws.ts`) warns on gaps but treats them as informational (teaching), not fatal.
- **The client store survives a `/ws` disconnect** (conversation lives in zustand, not
  the socket). Note: in *dev*, Vite's HMR can do a full page reload (e.g. on first-load
  dependency optimization or when its own HMR socket blips), which resets the store —
  that's a dev-server artifact, not app behavior; a production build never does this.

---

## Reminders that have bitten people

- **Billing:** the app strips `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` from the terminal's
  env before spawning a shell (M5) so an interactive `claude` uses the subscription,
  not metered API billing. Never `export` those keys in the shell running this app.

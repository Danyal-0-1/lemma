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
| M2 — ModelProvider + one real role | ✅ done | see `git log` |
| M3 — Full crew + approval gate + Spec | ✅ done | see `git log` |
| M4 — Spec tab + history + export | ✅ done | see `git log` |
| M5 — Workspaces + Terminal | ✅ done | see `git log` |
| M6 — Diff + Files + Checks | ✅ done | see `git log` |
| M7 — Explain (mentor) | ✅ done | see `git log` |
| M8 — Polish + learning pass | ✅ done | see `git log` |
| M9 — Headless AgentProvider | ▫ optional | — |
| R&D Studio — configurable research organization | ✅ implemented | working tree |
| Linux distribution — offline bundle, portable installer, Debian package | ✅ implemented | working tree |

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
- **Providers are a pure layer** (`providers/`): they never import the event bus, the
  DB, or config. They take messages, yield `TextDelta`/`StreamDone`. Callers (oneshot,
  later the orchestrator) own event emission and cost recording. This keeps them
  trivially testable and makes `MockProvider` a true drop-in for the real one.
- **Cost path:** `cost.record_and_summarize()` prices a turn from `config.toml`,
  persists a `CostRecord`, and returns the `cost_update` payload (session + day totals).
  It runs via `asyncio.to_thread` from async code because SQLite calls are blocking.
- **Two config sources, kept apart:** `settings.py` = secrets/paths from env/.env;
  `config.py` = crew choices (roles/budget/pricing) from committed `config.toml`.
- **The orchestrator is a hand-written state machine, no framework** (§3). The human
  gate blocks on an `asyncio.Event` inside a `SessionControl`; `control.py` holds the
  registry so REST `approve`/`cancel` can signal a running session by id.
- **Roles output JSON; parsing is liberal.** `parsing.py` strips a ```json fence (or
  finds the widest bracket span) then validates into the schema; on failure the
  orchestrator retries the turn ONCE with the validation error appended, then emits a
  graceful `error` (never crashes). The streamed JSON also shows in the Conversation.
- **Artifacts are append-only:** each IdeaDoc/Spec save is a new versioned row, so the
  UI can replay how an idea evolved (a run produced 9 ideadoc + 2 spec versions).
- **Accepted file-size exception:** `ideation/orchestrator.py` is ~310 lines (>250
  target). It's THE state machine; splitting the class would scatter one flow across
  files and hurt readability. The registry was already peeled off into `control.py`.
- **"Request changes" re-runs the whole round** with the feedback (simplification of
  §9's "PM decides re-entry point" — flagged in the orchestrator header comment).
- **Monaco runs offline and lazily.** `lib/monaco.ts` imports only `editor.api` + the
  JSON language (not the full monaco-editor, which bundles every language) and wires
  Vite `?worker` imports so no CDN is used. It's imported *inside* `MonacoJson.tsx`,
  which `SpecTab` loads via `React.lazy`, so Monaco is fetched only when you open the
  Raw view — keeping the initial bundle ~350kB instead of ~2.6MB.
- **`render_spec_markdown` (spec_render.py) is shared** by the export (M4) and will be
  reused for the workspace SPEC.md (M5) — one renderer, identical output everywhere.
- **Restore is read-only history:** a reloaded session's in-memory orchestrator/gate is
  gone, so an `awaiting_approval` session can't be resumed after a server restart —
  restore shows the transcript + artifacts for viewing/export, not for continuing.
- **Single `sessionId` in the store** (view + signal target), kept across the return to
  idle so a finished session can still be exported; `awaitingApproval` clears on idle.
- **⚠️ Billing and credential safety:** `shell_env.sanitized_env()` constructs a small
  allowlist instead of copying the backend environment. Provider keys, cloud tokens,
  credential variables, and agent sockets therefore stay out of terminal/check child
  processes. `test_pty.py` and `test_security.py` guard this — never weaken it.
- **PTY design:** `pty.fork()` + `os.execvpe` (controlling terminal set correctly for
  job control); non-blocking master fd read via `loop.add_reader` → ordered queue →
  ws; keystrokes are BINARY frames, resize is a TEXT control frame. Reaping is
  macOS-safe (close master → SIGHUP → `waitpid`, escalate to SIGKILL) run off the loop.
- **/pty is a separate socket** carrying raw bytes (not the JSON `/ws` envelope) — see
  ARCHITECTURE.md. Terminal registry is in-memory; a terminal is reaped on disconnect.
- **TerminalTab is Strict-Mode-safe:** if unmounted before its /pty connects, it opens
  a throwaway socket so the backend reaps the orphaned shell (dev double-mount → the
  extra shell is cleaned up, one live terminal remains).
- **Workspaces live OUTSIDE the repo** at `~/ai-company-workspaces/<slug>` (collision →
  `-slug-2`), git-inited with SPEC.md/spec.json/CLAUDE.md/aicompany.json. Directory is
  never deleted in v1. xterm loads lazily (build phase only), like Monaco.
- **The allowlisted child env is shared** (`app/shell_env.py::sanitized_env`) by BOTH
  the PTY terminal and Checks runner, so their credential boundary cannot drift.
- **Diff = working tree vs HEAD** (`git diff HEAD --numstat`) plus untracked from
  `git status --porcelain`. The Diff tab PULLS (Refresh + 5s poll only while visible),
  publishes totals to `store.diffCounts` for the sidebar `+/−`; no `diff_updated` event.
- **Checks:** commands in `aicompany.json`; run save-then-run (so the backend runs
  exactly what's shown), one-at-a-time per workspace (asyncio.Lock), stderr merged into
  stdout for ordered output; `check_started/output/finished` events → `store.checkRuns`
  badges. `read_file` has a path-traversal guard (must resolve inside the workspace).
- **Two git helpers** (`workspaces/gitutil.py`): `git_run` (must succeed) vs `git_output`
  (read-only, ignores non-zero — a `git show HEAD:new_file` "failing" is normal).
- **The mentor is just another model call.** `teach/explain.py` streams as role
  `mentor` using the SAME turn events (agent_turn_started/token_stream/completed), so the
  Conversation renders it for free (green) — no separate panel (§11). Uses the `explain`
  role model from config; mock returns a canned lesson.
- **Three Explain triggers, one path** (`lib/mentor.askMentor`): the build-phase composer
  (question), a floating "Explain this" on a Monaco selection (Diff modified side +
  Files), and a per-file "explain" link on diff rows. Each shows a "You" bubble then the
  mentor answers. The active review tab publishes `store.mentorContext` so questions are
  grounded (e.g. the diff summary / the open file).
- **Added a `user` role** to the Conversation (our optimistic "You" bubble); turns are
  appended via the generalized `appendTurn(turns, role, text)` store helper.
- **The state vault holds application history.** SQLite remains live state;
  `state_vault.py` commits a deterministic JSON projection to a separate local Git
  repository at `settings.git_vault_dir`. Credential-shaped fields and absolute
  workspace paths are removed; Lemma configures no remote and never pushes it.
  Research prompts and findings remain sensitive.
- **Linux distribution uses one verified payload.** `linux_install/build.sh` builds the
  production frontend and vendored Python tree entirely from pre-populated npm/uv
  caches, then emits a manifest-checked directory and archive. The receipt-managed
  portable installer consumes that bundle directly; `build-deb.sh` verifies and wraps
  the same tree under `/opt/lemma` instead of rebuilding dependencies.
- **Installed code and mutable state never share a lifecycle.** Replaceable payloads
  live under `~/.local/opt/lemma` or `/opt/lemma`; private config, the database/state
  vault, versioned writable source, and logs use XDG config/data/state directories.
  Normal upgrades and removal preserve those trees and `~/ai-company-workspaces`.
- **Linux artifacts have a narrow compatibility and trust envelope.** Vendored native
  dependencies bind a bundle to its architecture, compatible system libraries, and
  exact Python `major.minor` recorded in `PYTHON_ABI`. SHA-256 manifests protect
  integrity but are not signatures. The packaged runtime remains loopback-only and
  single-user; a `.deb` is not a production deployment boundary.
- **Never reuse a Linux release version for changed code.** The builder requires the
  frontend, backend package, and server versions to match; first launch seeds a writable
  backend source tree at `app-<version>`. Reusing a version would deliberately retain
  the earlier user tree, so bump all three version declarations for every code release.

---

## Reminders that have bitten people

- **R&D extension:** departments, agent duty cards, projects/tasks/findings, bounded
  meetings, and activity auditing live under `app/lab/` and `frontend/src/lab/`.
  Agents are prompt-only by construction; natural language never grants capabilities.
- **Host tools:** disabled unless `ENABLE_HOST_EXECUTION=true`. The PTY is a trusted-
  human convenience, not a sandbox. Never expose this backend beyond loopback.
- **Billing:** never export provider keys into a shell used to run coding CLIs. Lemma's
  child environment allowlist adds defense in depth but does not change external CLI
  billing contracts.
- **Linux releases:** build on the oldest compatible Linux target with the intended
  Python minor version, distribute through a trusted channel, and keep mutable XDG data
  out of release bundles. See `linux_install/README.md` before changing packaging.

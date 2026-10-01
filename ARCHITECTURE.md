# ARCHITECTURE.md — how the system fits together

<!-- READING ORDER: 6 — read once you've skimmed README + CLAUDE. -->

This document is the map. The original M0–M8 workbench remains intact, and the R&D
Studio adds a configurable research organization above it. The local build is a
single-user application; it is not a remotely deployable multi-tenant service.

---

## The big picture

```
┌────────────────────────── FRONTEND (Vite + React + TS) ─────────────────────┐
│ Activity rail │ Context explorer │ HQ / Org / Research / Knowledge / Evals │
│               │                  │ Meetings / Operations / Security / IDE   │
└──────▲────────┴────────▲─────────┴──────────────────────────▲───────────────┘
       │ REST actions    │ addressed WebSocket events         │ /pty (optional)
┌──────┴─────────────────┴────────────────────────────────────┴───────────────┐
│                        BACKEND (FastAPI, Python 3.12+)                       │
│ LocalOnlyMiddleware: loopback peer + Host + exact Origin                    │
│                                                                              │
│ Research Lab: evidence · claims · task DAG · dossiers · evals · policies    │
│   LabOrchestrator: prompt-only turns · bounded meetings · durable jobs       │
│   ModelProvider: Mock or LiteLLM → configured provider                      │
│                                                                              │
│ Original Workbench: ideation → approved Spec → workspace → review           │
│ Host tools (off by default): PTY terminal + argv checks + Git workspace      │
│                                                                              │
│ EventBus (live delivery) + SQLite/SQLModel (durable state and audit trail)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

The critical boundary is vertical: ordinary research agents can call only the model
provider. They cannot import or reach terminal, workspace, checks, environment,
connector, or secret APIs. `ENABLE_HOST_EXECUTION` unlocks trusted-human workbench
controls only. The optional M9 adapter sits on the host side of that boundary and
requires a second switch, an approved durable plan, an active workspace, and an
explicit executable path.

---

## Product areas

- **R&D Studio.** Create durable departments or temporary mission teams, define agent
  duty cards and communication scopes, capture checksum-addressed sources/excerpts,
  assign dependency-aware tasks, review findings and evidence-backed claims, run fixed
  roster meetings, compare models, export dossiers, and govern runs with project policy.
- **Original Workbench — Phase 0, Ideation.** A fixed crew (Generator → Researcher →
  Critic → PM) debates a seed and converges on a human-approved **Spec**.
- **Original Workbench — Phase 1, Build.** The approved Spec becomes a workspace; a
  trusted human may opt into a real terminal, then inspect diffs and bounded checks.

The workbench UI remains phase-aware: controls that do nothing in the current phase
are not rendered.

---

## Two provider layers (never conflated)

1. **`ModelProvider`** *(M2)* — raw chat completions for the crew and the Explain/mentor
   feature. Async + streaming, with LiteLLM underneath so `deepseek/…`, `anthropic/…`,
   `openai/…`, and local OpenAI-compatible endpoints are one interface. A `MockProvider`
   implements the same shape for zero-cost development.
2. **`AgentProvider`** *(M5/M9)* — coding agents that edit files and run commands. The
   default remains the PTY terminal where the user drives an agent interactively. An
   optional Claude headless adapter is implemented behind two configuration switches
   and a separate persisted approval gate. It uses fixed argv, a sanitized environment,
   workspace-root validation, bounded time/output, and process-group cleanup. It is
   still a trusted host process—not a sandbox—and its capability list records approved
   intent rather than enforcing OS permissions.

**Why no CrewAI/LangGraph:** the ideation loop is a sequential state machine of ~4 steps
with one human gate. A framework would hide exactly the mechanics this codebase exists to
teach, add dependency churn, and save nothing. So it's a plain, readable orchestrator
class. LangGraph could be revisited if the flow ever needs real branching.

---

## The event pipe *(M1)*

Everything the user sees stream in — crew tokens, artifacts, cost updates, build logs —
travels over **one** WebSocket, `GET /ws`, as a uniform envelope:

```json
{ "v": 1, "seq": 412, "ts": "2026-07-21T18:04:11.532Z",
  "session_id": "ideation_9f3a", "event": "token_stream", "payload": { } }
```

An in-process **EventBus** (pub/sub) is where every backend subsystem publishes; the
`/ws` endpoint subscribes and fans messages out to the browser. `seq` is a
per-connection monotonically increasing integer so the client can detect (and warn on)
dropped/out-of-order messages. REST is used for **actions** (create session, approve,
run check); the WebSocket is used for **streaming results**. The full event table lives
in PROMPT.md §7.

### Why PTY traffic is a *separate* socket

Terminal bytes are raw and high-volume. Routing them through the JSON event envelope
would force base64 encoding and pollute the event log. So the PTY uses its own socket,
`GET /pty/{terminal_id}`, carrying raw bytes both ways plus a small JSON control message
for resize (`{"type":"resize","cols":..,"rows":..}`). Keeping bytes off the event bus
keeps both sides simple.

---

## Persistence *(M3)*

SQLite (via SQLModel) at `backend/data/app.db` (gitignored). Original tables store
ideation sessions, messages, append-only artifacts, cost, and workspaces. Lab tables
store departments, agents, projects, tasks, runs, results, findings, meetings, ordered
meeting messages, and append-only activity records. Evidence/workflow tables add source
documents and exact excerpts, reviews, claims, evidence edges, meeting outcomes/actions,
task dependencies, trace links, policy, exact model-call provenance, templates,
evaluations/scores, and approval-gated automation. A rebuildable local FTS5 index ranks
research content; SQLite remains canonical. Alembic owns schema evolution;
startup upgrades to its single current head and validates that every SQLModel table and
column exists before serving requests. A legacy `create_all()` database is adopted by
the `0001_current_schema` baseline without deleting its rows.

Before applying any pending revision to a database with application tables, startup
uses SQLite's online-backup API to create a consistent snapshot in `data/backups/`,
runs an integrity check, and records its size, SHA-256, and Alembic revision in a JSON
sidecar. `app.db_admin` also provides explicit backup, verification, migration, and
restore commands. Restore requires its checksum sidecar, preserves the current database
first, performs an atomic replacement, and shares a process lock with the backend.

SQLite remains the live transactional source of truth. `state_vault.py` also renders a
deterministic `lemma-state.json`, with credential-shaped fields redacted, into a
separate local Git repository. It snapshots at startup, shutdown, and periodically
while the backend is running, appears as the built-in **Lemma state vault** Source
Control workspace, and never adds a remote or pushes automatically. The snapshot
contains research content, so its local Git history remains sensitive despite these
redactions and the removal of absolute workspace paths.

---

## Offline Linux release and installed runtime

`linux_install/build.sh` is a Linux-only, offline release pipeline. It consumes the
committed npm and uv lockfiles from pre-populated local caches, verifies that the
frontend, backend, and server versions agree, and emits an architecture-specific
directory plus `.tar.gz` and SHA-256 checksum. The bundle contains the production web
assets, a source seed, vendored Python dependencies, launchers, top-level portable
install/uninstall scripts, a complete file manifest, build metadata, and third-party
notices. `build-deb.sh` verifies that same bundle before placing it under `/opt/lemma`
and adding Debian command, desktop, and user-systemd integration; it does not resolve
or download a second dependency set.

The portable installer defaults to `~/.local/opt/lemma` and records every owned path
for exact upgrades and removal. The installed program and mutable user state remain
separate:

| Layer | Default installed location | Lifecycle |
|---|---|---|
| Replaceable application payload | `~/.local/opt/lemma` or `/opt/lemma` | Replaced by portable or Debian upgrades |
| Private configuration | `${XDG_CONFIG_HOME:-~/.config}/lemma/.env` | Created mode `0600`; preserved on normal removal |
| Live database and local state vault | `${XDG_DATA_HOME:-~/.local/share}/lemma/data/` | Persistent, private user data |
| Versioned writable source copy | `${XDG_DATA_HOME:-~/.local/share}/lemma/app-<version>/` | Created and Git-initialized on first launch |
| Fallback logs | `${XDG_STATE_HOME:-~/.local/state}/lemma/` | Persistent operational state |
| Project repositories | `~/ai-company-workspaces/` by default | Never part of the application payload |

On first launch, `lemma-server` copies the bundled source seed into the versioned user
tree and links its `backend/data` path to the persistent XDG data directory. The static
frontend and vendored Python packages continue to run from the replaceable install
root. This lets package upgrades preserve research state without making `/opt/lemma`
user-writable.

Native Python dependencies make a release specific to its CPU architecture, compatible
system C libraries, and exact Python `major.minor`. The builder records that value in
`PYTHON_ABI`; `lemma-server` refuses a different interpreter, and the Debian package
depends on the matching versioned Python package. Release manifests and archive/package
checksums detect corruption or modification. The bundle also carries a manifest-covered,
lock-derived CycloneDX SBOM. Detached minisign authentication of the manifest and
archive/package is available but optional; verification becomes a hard requirement only
when the operator supplies an independently trusted public key. Installed builds retain
the same fixed loopback ports and single-user security model as development; packaging
does not make Lemma suitable for remote or multi-user deployment.

---

## Current state (evidence-rich R&D Studio plus M0–M9)

- **R&D control plane:** Knowledge captures immutable source identity and exact excerpts,
  assembles bounded source packets, records human reviews and claim/evidence stance, and
  provides local full-text search plus JSON/Markdown project dossiers. Task dependencies
  are cycle-checked and enforced at run start; meeting decisions/actions can be promoted
  into tasks; trace links connect research to downstream work. Operations exposes durable
  run attempts, cancel/retry lineage, exact prompt/model provenance, cumulative token/cost
  limits, model allowlists, recorded data classification, concurrency limits, validated
  template instantiation, and startup recovery for interrupted background work.
  Evaluations run models sequentially with cancellation, usage/latency records, and human
  scores. Source context, transcripts, output, and subprocesses are explicitly bounded.

- **M0:** the shell — FastAPI `GET /health` + the three-panel VS Code-dark layout.
- **M1:** the event pipe — `events.py` (Event + EventBus + Sequencer) and `ws.py`
  (`/ws`: hello, pump, heartbeat, clean disconnect); `demo.py` + `POST /api/demo`.
  Frontend: `ws.ts` (reconnect + seq-gap, Strict-Mode-safe), zustand `appStore`,
  resizable three-panel layout, role-colored streaming Conversation, live StatusBar dot.
- **M2:** the ModelProvider layer. `providers/base.py` is the interface
  (`stream_chat` yields `TextDelta`… then `StreamDone`); `mock_provider.py` (free) and
  `litellm_provider.py` (real, with retry/usage) implement it; `factory.py` picks one.
  `config.py` loads `config.toml`; `db.py`/`models.py` add SQLite + `CostRecord`;
  `cost.py` prices+persists+summarizes; `oneshot.py` + `POST /api/oneshot` stream a
  single Generator turn and move the cost meter. Providers are a PURE layer — they never
  import the bus, DB, or config; the caller owns emission and billing.

- **M3:** the ideation crew. `ideation/schema.py` (IdeaDoc + Spec with validators),
  `roles.py` (the verbatim role prompts), `parsing.py` (JSON extraction + one-shot
  retry), `repo.py` (session/message/artifact persistence, append-only artifacts),
  `orchestrator.py` (the state machine: Generator→Researcher→Critic→PM→gate, budget
  guard, cancel), and `control.py` (the registry + start/resolve/cancel the REST layer
  calls). Frontend: the composer starts a session, the store handles the approval
  events, and `ApprovalBar` docks the Approve / Request changes / Reject decision.

- **M4:** the artifacts become visible + portable. `spec_render.py` renders a Spec to
  markdown (reused for export and, next, SPEC.md); `export.py` + `POST .../export`
  produce one downloadable file. Frontend: `SpecTab` (version switchers, a recursive
  `JsonTree`, a lazily-loaded offline `MonacoJson` for the raw view, and the idea
  evolution), the store now accumulates `artifacts` and can `restoreSession` from the
  DB, and the `Sidebar` lists/restores past sessions.

- **M5:** Phase 1 begins. `workspaces/manager.py` turns a Spec into a real git repo
  under `~/ai-company-workspaces/<slug>` (SPEC.md/spec.json/CLAUDE.md/aicompany.json);
  `build/coordinator.py` emits `workspace_created` + `phase_changed(build)`;
  `terminal/pty_service.py` runs an interactive shell over the **separate `/pty`
  socket** with an allowlisted child environment and macOS-safe reaping. Frontend: the
  xterm `TerminalTab` (lazy-loaded, stays mounted across tab switches), phase-aware
  build tabs, and Open-in-editor / Reveal.

- **M6:** the review loop. `workspaces/diff.py` (changes vs HEAD + untracked),
  `workspaces/files.py` (list/read with a path-traversal guard), `workspaces/checks.py`
  (run saved commands with the shared sanitized env, one at a time, streaming
  `check_*` events). `app/shell_env.py` centralizes the child-environment allowlist used
  by both the terminal and checks. Frontend: DiffTab (poll-while-visible + Monaco diff + sidebar
  +/− counts), read-only FilesTab, and ChecksTab (edit/save/run + green/red badges).

- **M7:** the teaching layer. `teach/explain.py` + `POST /api/explain` stream a MENTOR
  answer over the existing turn events (role "mentor") — grounded by the active tab's
  content (`store.mentorContext`). Three triggers, one path (`lib/mentor.askMentor`): the
  build-phase composer, a floating "Explain this" on a Monaco selection, and per-file
  explain links. No new event types — it composes the layers already built.

- **M8:** polish. Workspace archive/restore (status flip, directory kept) with a
  collapsible **History** section; error **toasts** (feed + top-right); **keyboard
  shortcuts** (new session, focus Diff/Terminal/Checks — `buildTab` lifted into the
  store); README first-run walkthrough + troubleshooting; `learning/exercises.md`; and a
  simplicity audit (exactly three panels, phase-aware tabs, no inert controls).

- **M9:** optional headless coding. Operations persists the request, plan, approved
  capability intent, decision, output, and failure state. Execution stays off until
  host execution and the separate M9 flag are both enabled; only an explicit absolute
  Claude executable is accepted, and each plan still needs human approval.

All original milestones and the R&D Studio are implemented. Model calls use the shared
provider layer and cost records; durable outcomes go to SQLite; addressed live progress
uses the event bus. See [SECURITY.md](SECURITY.md) before changing any capability or
deployment boundary.

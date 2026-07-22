# ARCHITECTURE.md — how the system fits together

<!-- READING ORDER: 6 — read once you've skimmed README + CLAUDE. -->

This document is the map. It's updated whenever the structure changes (PROMPT.md §1
rule 9). Right now (M0) only the skeleton exists; sections marked *(arrives in Mn)*
describe what the finished shape will be so you can see where each milestone plugs in.

---

## The big picture

```
┌────────────────────────── FRONTEND (Vite + React + TS) ─────────────────────┐
│ Sidebar           │ Conversation            │ Review pane (phase-aware):    │
│ sessions,         │ crew debate · mentor ·  │ Diff | Terminal | Files |     │
│ workspaces,       │ approval bar · composer │ Checks | Spec                 │
│ history           │                         │                               │
└────▲───────────────▲────────────────────────────────────────▲───────────────┘
     │ REST (actions)│ WebSocket /ws (events)                 │ WebSocket /pty
┌────┴───────────────┴────────────────────────────────────────┴───────────────┐
│                        BACKEND (FastAPI, Python 3.12)                        │
│                                                                              │
│  EventBus (in-process pub/sub) ── every subsystem publishes; /ws fans out    │
│                                                                              │
│  IdeationOrchestrator (custom state machine — NO agent framework)   (M3)     │
│      └── ModelProvider (LiteLLM) → DeepSeek / Anthropic / OpenAI     (M2)     │
│  BuildCoordinator                                                   (M5)      │
│      └── AgentProvider (v1: PTY terminal)                            (M5)     │
│  WorkspaceManager (dirs, git init, diff, checks, archive)          (M5/M6)    │
│  PtyService (os.openpty + shell, resize, sanitized env)             (M5)      │
│  Persistence (SQLite via SQLModel): sessions, messages, artifacts   (M3)     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Two phases

- **Phase 0 — Ideation.** A crew of AI roles (Generator → Researcher → Critic → PM)
  debate a seed idea and converge on a human-approved **Spec**.
- **Phase 1 — Build.** The approved Spec becomes an isolated workspace directory; the
  user drives a real coding agent (`claude`/`codex`) in the embedded terminal, and the
  app streams diffs, check results, and mentor explanations back into the UI.

The UI is **phase-aware**: controls that do nothing in the current phase are not rendered.

---

## Two provider layers (never conflated)

1. **`ModelProvider`** *(M2)* — raw chat completions for the crew and the Explain/mentor
   feature. Async + streaming, with LiteLLM underneath so `deepseek/…`, `anthropic/…`,
   `openai/…`, and local OpenAI-compatible endpoints are one interface. A `MockProvider`
   implements the same shape for zero-cost development.
2. **`AgentProvider`** *(M5)* — coding agents that edit files and run commands. In v1
   this is deliberately thin: the PTY terminal where the user drives the agent
   interactively (their subscription, zero billing ambiguity). A headless variant is a
   future option (M9), not v1.

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

SQLite (via SQLModel) at `backend/data/app.db` (gitignored). Tables: `IdeationSession`,
`Message`, `Artifact` (append-only — each new version is a new row, so you can watch an
idea evolve), `CostRecord`, `Workspace`. No migrations in v1 — tables are recreated in
dev.

---

## Current state (through M2)

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

The orchestrator (M3), workspaces + terminal (M5), diff/checks (M6), and explain (M7)
arrive next — all of them simply `event_bus.publish(...)` and lean on the provider layer.

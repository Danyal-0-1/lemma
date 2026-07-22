# LEARNING_PATH.md — read this code in the right order

<!-- READING ORDER: 7 -->

This codebase is meant to be **read and retyped**, not just run. This file is your
syllabus: for each milestone it lists the files to read in order, what concept each
teaches, one file to **RETYPE**, and a few exercises ("change X, predict what breaks,
verify"). It grows one section per milestone.

> How to retype: copy the target file into `learning/retyped/`, then type it out by hand
> without looking more than one line ahead. Then `diff` your copy against the original.
> The gaps you find are the things you didn't actually understand yet.

---

## M0 — Scaffold

**What this milestone teaches:** how a full-stack project is wired together before any
features exist — the dev commands, where config and secrets live, and the smallest
possible "hello, it's alive" from both the backend and the frontend.

**Read in this order:**

1. [`README.md`](README.md) — what the app is and how to run it.
2. [`CLAUDE.md`](CLAUDE.md) — the conventions every file follows, and the decisions log.
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) — the runtime picture you're building toward.
4. [`Makefile`](Makefile) — the four commands (`install`, `backend`, `frontend`, `dev`).
5. [`scripts/dev.sh`](scripts/dev.sh) — how two servers start and stop together (the
   `trap` + `wait` pattern). Teaches: process groups and clean shutdown.
6. [`backend/.env.example`](backend/.env.example) — every configuration knob, documented.
   Teaches: the secret/config boundary and the billing warning.
7. [`backend/app/settings.py`](backend/app/settings.py) — typed config from environment
   variables. Teaches: pydantic-settings and why `HOST` is guarded to `127.0.0.1`.
8. [`backend/app/main.py`](backend/app/main.py) — the FastAPI app and `GET /health`.
   Teaches: the minimal shape of a web server and a startup lifecycle.
9. [`frontend/src/theme.css`](frontend/src/theme.css) — the VS Code Dark+ color tokens.
10. [`frontend/src/App.tsx`](frontend/src/App.tsx) — the three-panel layout skeleton.

**RETYPE THIS → [`backend/app/main.py`](backend/app/main.py).** It's short, it's the
entry point, and retyping it forces you to notice how a FastAPI app, a route, and a
startup check are declared. Everything else in the backend hangs off this file.

**Exercises:**

1. In `settings.py`, change the default `PORT` and run `make backend`. Predict which URL
   `/health` now answers on, then verify with `curl`.
2. Break `main.py` on purpose: rename `health()` to `healthz()` but leave the route path
   `/health`. Predict whether the server still starts and whether `/health` still works.
   Run it and see. (Lesson: the function name and the route path are independent.)
3. Set `HOST=0.0.0.0` in `backend/.env` and start the backend. Predict what happens.
   (Lesson: read the startup guard in `settings.py`/`main.py`.)

---

## M1 — Event pipe with fake events

**What this milestone teaches:** how the whole app streams live updates. One
WebSocket carries a uniform envelope; an in-process pub/sub bus decouples "something
happened" from "send it to the browser"; and the frontend keeps that socket alive,
turns events into state, and renders them. This is the backbone every later feature
plugs into.

**Read in this order (backend first, then follow one event from publish to pixel):**

1. [`backend/app/events.py`](backend/app/events.py) — the `Event` envelope, the
   `EventBus` (subscribe/publish/unsubscribe), and the `Sequencer` (per-connection
   `seq`). Teaches: pub/sub and why `seq` is stamped at send time.
2. [`backend/app/ws.py`](backend/app/ws.py) — one `/ws` connection: hello, the pump
   task, the 20s heartbeat, and clean disconnect. Teaches: running concurrent
   asyncio tasks and always cleaning up in `finally`.
3. [`backend/app/demo.py`](backend/app/demo.py) — the scripted crew round that proves
   the pipe end-to-end with zero cost. Teaches: streaming by chunking + delays.
4. [`backend/app/main.py`](backend/app/main.py) — how `/ws` and `POST /api/demo` are
   registered (thin routes that delegate).
5. [`frontend/src/lib/events.ts`](frontend/src/lib/events.ts) — the TS mirror of the
   envelope. Teaches: typing wire data.
6. [`frontend/src/lib/ws.ts`](frontend/src/lib/ws.ts) — the client: reconnect backoff,
   seq-gap warnings, and the Strict-Mode-safe `close()`. Teaches: resilient sockets.
7. [`frontend/src/store/appStore.ts`](frontend/src/store/appStore.ts) — `applyEvent`,
   the switch that turns each event into UI state. Teaches: zustand + immutable updates.
8. [`frontend/src/panels/Conversation.tsx`](frontend/src/panels/Conversation.tsx) and
   [`App.tsx`](frontend/src/App.tsx) — where state becomes pixels, and the single
   `useEffect` that owns the socket's lifecycle.

**RETYPE THIS → [`backend/app/events.py`](backend/app/events.py).** It's the heart of
the architecture and small enough to retype in one sitting. If you understand why
`publish` is synchronous and why `seq` is assigned in the `Sequencer` (not the bus),
you understand the event pipe.

**Exercises:**

1. Add a new field `mood` to `Event` in `events.py` with a default, then log it in
   `ws.py`. Predict whether the frontend breaks (hint: it ignores unknown fields).
   Verify by playing the demo.
2. In `demo.py`, lower `CHUNK_DELAY_SECONDS` to `0` and raise it to `0.3`. Predict how
   the Conversation feels in each case, then watch the demo to confirm.
3. Break the pipe on purpose: in the `Sequencer`, comment out `self._seq += 1`. Predict
   what the client's console shows (hint: read the gap-detection code in `ws.ts`), then
   run it and read the warning.

---

## M2 — ModelProvider + one real role

**What this milestone teaches:** how the app talks to a language model behind a clean
interface — so the same code runs against a free mock or a real API — and how it turns
token usage into a real, persisted cost meter. This is the "call an AI and bill it"
plumbing the whole crew (M3) is built on.

**Read in this order (the interface, then both sides, then the money, then the seam):**

1. [`backend/app/providers/base.py`](backend/app/providers/base.py) — the
   `ModelProvider` Protocol and the `ChatMessage` / `TextDelta` / `StreamDone` types.
   Teaches: structural interfaces + a streamed tagged union.
2. [`backend/app/providers/mock_provider.py`](backend/app/providers/mock_provider.py) —
   the free, canned implementation. Teaches: why mock mode is a real feature.
3. [`backend/app/providers/litellm_provider.py`](backend/app/providers/litellm_provider.py)
   — the live implementation: streaming, retry-with-backoff, usage capture. Teaches:
   handling flaky networks without crashing a turn.
4. [`backend/app/providers/factory.py`](backend/app/providers/factory.py) — one place
   decides mock vs. live. Teaches: the factory pattern.
5. [`backend/app/config.py`](backend/app/config.py) — validating `config.toml` into
   typed models. Teaches: `tomllib` + trusting external files only after validation.
6. [`backend/app/models.py`](backend/app/models.py) + [`db.py`](backend/app/db.py) —
   the first table (`CostRecord`) and the SQLite engine. Teaches: SQLModel basics.
7. [`backend/app/cost.py`](backend/app/cost.py) — price → persist → summarize.
   Teaches: aggregate queries (`func.sum`) and keeping side effects out of pure logic.
8. [`backend/app/oneshot.py`](backend/app/oneshot.py) — where provider + cost + events
   meet, end to end. Teaches: composing the layers; `asyncio.to_thread` for blocking IO.

**RETYPE THIS → [`backend/app/providers/base.py`](backend/app/providers/base.py).** It's
the contract everything else depends on. If you can reproduce the `stream_chat` signature
and the `TextDelta | StreamDone` union from memory, you understand the provider layer.

**Exercises:**

1. Add a fourth idea to the Generator's canned answer in `mock_provider.py`. Predict
   whether the cost meter changes when you run "One real turn" (hint: usage is estimated
   from the answer's length). Verify.
2. In `config.toml`, double the `output` price for `deepseek/deepseek-chat`. Predict how
   the meter changes on the next mock turn, then run it and compare.
3. Break pricing on purpose: delete the `deepseek/deepseek-chat` entry from
   `[pricing]`. Predict what the meter shows and what the logs say (hint: read
   `estimate_usd`), then run it.

---

*(M3 and beyond are appended as each milestone lands.)*

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

*(M1 and beyond are appended as each milestone lands.)*

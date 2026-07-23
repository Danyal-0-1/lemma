# Exercises — every "change X, predict, verify" in one place

These are collected from [`../LEARNING_PATH.md`](../LEARNING_PATH.md). Do them in order,
or jump to a milestone you're studying. Each one is: **change something → predict what
happens → run it → see if you were right.** Being wrong is the point — that's where the
learning is. (Use git to undo: `git stash` or `git checkout -- <file>`.)

---

## M0 — Scaffold

1. In `backend/app/settings.py`, change the default `PORT` and run `make backend`.
   Predict which URL `/health` answers on, then verify with `curl`.
2. In `backend/app/main.py`, rename `health()` to `healthz()` but keep the route path
   `/health`. Predict whether the server starts and `/health` still works. (Lesson: the
   function name and the route path are independent.)
3. Set `HOST=0.0.0.0` in `backend/.env` and start the backend. Predict what happens
   (Lesson: the startup guard).

## M1 — Event pipe

1. Add a field to `Event` in `events.py` with a default; play the demo. Predict whether
   the frontend breaks (it ignores unknown fields).
2. In `demo.py`, set `CHUNK_DELAY_SECONDS` to `0`, then `0.3`. Predict how the
   Conversation feels each way.
3. Comment out `self._seq += 1` in the `Sequencer`. Predict the client console warning
   (read the gap detection in `ws.ts`), then run it.

## M2 — ModelProvider + cost

1. Add a fourth idea to the mock Generator answer; predict whether the cost meter changes
   (usage is estimated from length).
2. Double the `output` price for `deepseek/deepseek-chat` in `config.toml`; predict the
   meter on the next mock turn.
3. Delete the `deepseek/deepseek-chat` price entry; predict the meter + logs
   (`estimate_usd`).

## M3 — Crew + gate + Spec

1. Set `MAX_FEATURES = 4` in `schema.py`; the mock PM emits 3, so predict whether a run
   still reaches the gate. Then raise the mock PM's Spec to 5 features and predict again
   (watch the retry fire).
2. Set `[budget] max_session_tokens = 1`; predict how far a run gets before
   `budget_exceeded`.
3. Make `extract_json` in `parsing.py` return `"not json"`; predict what the founder sees
   (retry once, then a graceful error bubble).

## M4 — Spec tab + history + export

1. Change a string value's color in `JsonTree.tsx`; predict everywhere it changes.
2. Add a footer to `render_spec_markdown`; predict whether it appears in the export AND
   (later) SPEC.md.
3. Open a past session, then reload the page; predict what the sidebar shows and whether
   the Spec tab is empty until you click a session.

## M5 — Workspaces + Terminal

1. Start with `ANTHROPIC_API_KEY=test123 make dev`, open a workspace terminal, run
   `echo $ANTHROPIC_API_KEY`. Predict the output (**empty** — the whole point). Then
   comment out the two `env.pop(...)` lines in `shell_env.py` and try again.
2. Change the commit message in `manager.py`; predict where you'd see it
   (`git -C ~/ai-company-workspaces/<slug> log`).
3. Open a workspace, switch to Spec and back to Terminal; predict whether your shell
   survives (`echo $$` before/after — same PID = same shell).

## M6 — Diff + Files + Checks

1. `echo hi > x.txt` in the terminal, then open the Diff tab (don't Refresh). Predict how
   long until it appears (the 5s poll).
2. Add a check `sleep 2 && echo done`, run it, immediately run it again. Predict what
   happens (the per-workspace lock).
3. In `diff.py`, change `git diff HEAD` to `git diff`; predict what the Diff tab shows
   after you *stage* a change (`git add`) in the terminal.

## M7 — Explain (mentor)

1. Add a joke to the MENTOR prompt's last line (`roles.py`); predict where it shows up,
   then Explain some code.
2. Ask "what changed?" with the Diff tab open, then with the Files tab open on one file.
   Predict how the answers differ (`mentorContext`).
3. Explain one line vs. a whole function; predict how the answer's specificity changes.

## M8 — Polish

1. Archive the active workspace; predict what happens to the build pane and the sidebar,
   and where the workspace goes. Restore it and predict whether the terminal reopens.
2. Trigger an error (e.g. `MOCK_LLM=false` with no key, then "One turn"); predict where
   it shows up (a toast AND the conversation feed).

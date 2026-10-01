<!-- READING ORDER: 1 — start here. -->
# Lemma

> *Lemma* (Greek *lēmma*): a small proven step on the way to a bigger theorem. Each milestone you read and retype is one.

A **local-first R&D operating system** for assembling small teams of AI research
agents. Create departments or temporary mission teams, give each agent a name and a
structured duty card, assign research work, and bring selected agents into bounded
meeting rooms where they share findings and produce a synthesis.

Lemma also keeps its original product-ideation and build workbench: a four-role crew
can turn a rough idea into a build-ready spec, then hand it to a coding agent you drive
in an embedded terminal with live diffs, checks, and a built-in mentor.

The interface borrows the dense activity rail, explorer, editor, and inspector model
from VS Code. It is **not** a replacement for your editor: it is the control plane for
your research organization, its conversations, and its reviewed outputs.

> **This is a learning codebase.** Every file is heavily commented and ranked with a
> `READING ORDER`. See [`LEARNING_PATH.md`](LEARNING_PATH.md) for the reading/retyping
> plan and [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces fit.

---

## Status

Built milestone by milestone (see [`PROMPT.md`](PROMPT.md) §14). Current progress lives
in [`CLAUDE.md`](CLAUDE.md) under *Milestone status*, and in `git log --oneline`.

**The evidence-rich R&D Studio and M0–M8 work end to end; M9 is available as an
explicitly gated option.** Alongside departments, agents, projects, tasks, meetings,
and findings, Lemma now includes captured-source provenance, exact excerpts, human
reviews, claims/evidence links, dependency-aware task queues, searchable history,
project dossiers, model comparisons, per-project policies, retryable run history, and
reusable templates. The whole research path is demoable in mock mode with no keys or
cost. Optional headless coding remains disabled unless the operator crosses every
separate approval and configuration gate.

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

## Database backups and migrations

Startup applies versioned Alembic migrations automatically. Before changing any
existing schema, Lemma creates a WAL-consistent SQLite snapshot under
`backend/data/backups/`, runs a full integrity check, and writes a checksum metadata
sidecar. Fresh databases do not create an empty backup.

```bash
make db-backup                         # safe while Lemma is running
make db-migrate                        # explicit upgrade to the current schema
cd backend
uv run python -m app.db_admin verify data/backups/<backup>.db --require-metadata
uv run python -m app.db_admin restore data/backups/<backup>.db --yes
```

Stop Lemma before `migrate` or `restore`; the backend holds a database lock so a
restore cannot replace a database in use. Restore verifies the backup and its SHA-256
sidecar, then makes a verified `pre_restore` backup of the current database before an
atomic replacement. These local backups contain readable research content and are not
encrypted or authenticated release artifacts.

---

## Packaged Linux installation

Linux releases can be built as an offline, per-architecture bundle and optionally
wrapped in a Debian package:

```bash
make linux-bundle
make linux-deb BUNDLE=linux_install/dist/lemma-<version>-linux-<arch>
```

Every artifact carries a lock-derived CycloneDX dependency SBOM. Release operators
can optionally add detached minisign signatures without changing the normal unsigned
workflow. The build requires pre-populated npm and uv caches. See the
[`linux_install` guide](linux_install/README.md) for prerequisites, portable and
Debian installation, signing and verification, upgrades, data locations, security
notes, and limitations.

---

## R&D Studio walkthrough (mock mode, ~5 minutes)

1. Open **Organization** from the activity rail and create a department or mission
   team.
2. Add two or three agents. Give each one a role, mission, duties, the issues it must
   consider, ranked priorities, and a communication scope. These fields form its Duty
   Card; they do not grant tools or machine permissions.
3. Open **Research**, create a project, then create an editable task with one assigned
   agent, research objective, context, expected output, and any prerequisite tasks.
4. Open **Knowledge** to capture a source, preserve a checksum and exact excerpt, link
   it into the task's bounded source packet, and run the task. Review its finding,
   record a claim, attach supporting or contradicting evidence, search the local FTS5
   index, and export the project's Markdown dossier.
5. Open **Meetings**, choose a project, facilitator, and permitted participants, and
   write an agenda. Running the room collects one bounded contribution per participant
   and then asks the facilitator for a synthesis. Record the human outcome and action
   items, then promote an action into a traceable research task.
6. Use **Evaluations** for a bounded side-by-side model comparison and human scoring.
   Use **Operations** to inspect/cancel/retry attempts, set model allowlists and
   cumulative budgets, and create or instantiate reusable templates.
7. Use **HQ** for the organization overview and **Security** for capability boundaries.
   Open **Workbench** for the original ideation crew, specs, files, diffs, checks,
   terminal, and mentor.

> Research outputs are model syntheses, not automatically verified evidence. The
> secure default gives research agents no browser, shell, filesystem, connector, or
> secret access. Add and verify sources before relying on important claims.

## Code workbench

The first four activity-rail tools provide a VS Code-style view of the selected
workspace:

- **Explorer** shows a bounded project tree and opens text files in a read-only Monaco
  editor with tabs and breadcrumbs.
- **Search** finds text across the workspace without following symlinks or exposing
  credential files, generated dependencies, or the local application database.
- **Source Control** shows the current branch, upstream, ahead/behind counts, staged
  and working changes, and bounded patches. Stage, unstage, commit, and confirmed push
  are available only after the operator enables host execution.
- **Terminal** is a real local PTY for the selected workspace and remains visibly
  locked until `ENABLE_HOST_EXECUTION=true` is set and the backend is restarted.

Use the Account and Settings buttons at the bottom of the activity rail for local
runtime status, System/Dark/Light/Gray themes, and editor preferences. System theme
tracks operating-system appearance changes live; preferences remain in browser local
storage. Git pushes accept only the checked-out branch's configured HTTPS or SSH
upstream, never force, embedded credentials, hooks, global Git configuration, or
interactive credential prompts.

## Original workbench walkthrough (mock mode, ~2 minutes)

1. **Start an ideation session.** In the center composer, type an idea (e.g. *"a tool to
   plan weekly meals"*) and press **Enter**. Four AI roles — Generator, Researcher,
   Critic, PM — debate it, streaming into the conversation.
2. **Approve the Spec.** When the crew pauses, the approval bar appears. Click **Request
   changes**, type feedback, and watch it run another round — or click **Approve**. The
   right pane's **Spec** tab shows every version (and the idea's evolution).
3. **Create a workspace.** In the Spec tab, click **Create workspace**. The app makes a
   real git repo under `~/ai-company-workspaces/<slug>` and switches to the build phase.
4. **Use the terminal (optional).** Host execution is locked on a fresh install. If
   you intentionally set `ENABLE_HOST_EXECUTION=true`, the **Terminal** tab is a real
   human-operated shell inside the workspace. Child processes receive a minimal
   environment rather than the backend's provider credentials.
5. **Review the diff.** Open the **Diff** tab — your new file shows with `+/−` counts
   (also on the sidebar). Click it for a Monaco diff.
6. **Run a check.** In the **Checks** tab, click **+ Add**, set the command to `echo ok`,
   and **Run** → green ✓. Try `false` → red ✗. Commands are parsed as argument lists;
   shell operators run only when you deliberately invoke a shell such as
   `/bin/sh -c '…'`.
7. **Ask the mentor.** Select some code in Diff/Files and click **Explain this**, or ask
   *"what does this diff do?"* in the composer. The mentor answers in the conversation.
8. **Archive when done.** Hover a workspace in the sidebar and click **archive** — it
   moves to **History**, where you can **restore** it later.

Keyboard: **Cmd/Ctrl+N** new session; in build, **Cmd/Ctrl+Shift+D / T / C** jump to
Diff / Terminal / Checks.

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
- constructs a minimal child-process environment instead of copying the backend's
  environment. Provider keys, cloud tokens, credential variables, and agent sockets
  stay out of the embedded terminal and checks runner.

This is enforced in `backend/app/terminal/pty_service.py` (and `backend/app/shell_env.py`,
which the Checks runner shares).

### Optional approval-gated headless coding (M9)

The interactive terminal remains the default coding workflow. To expose the optional
Claude headless adapter, all of these must be true:

```bash
ENABLE_HOST_EXECUTION=true
LEMMA_ENABLE_HEADLESS_CODING=true
LEMMA_HEADLESS_AGENT_EXECUTABLE=/absolute/path/to/claude
LEMMA_HEADLESS_AGENT_TIMEOUT_SECONDS=900
```

Restart Lemma, create a plan against an active workspace in **Operations →
Automation**, review its request, plan, and recorded capability intent, then approve
and run it as a separate action. The backend accepts only the audited Claude adapter,
uses fixed arguments rather than a shell, strips credentials from its environment,
confines its working directory to the configured workspace root, bounds time/output,
and kills the process group on cancellation or shutdown.

This remains a trusted host process, not an OS sandbox: the external CLI runs with
your user permissions, and its recorded capability list is approval/audit context,
not filesystem or network isolation. Confirm the CLI's login and subscription or
metered billing behavior before every real use. Leave either switch off if you do not
need it.

---

## Security posture

Lemma refuses non-loopback binding with no bypass. It checks the network peer, Host,
and exact browser Origin; validates WebSocket origins; denies UI framing; disables
host and headless execution by default; uses one-use terminal capabilities; bounds
model output, linked-source context, cumulative run budgets, meetings, subprocess
time/output/input; and keeps ordinary research agents entirely separate from host
tools. Exact prompts, policy snapshots, model usage, and retry lineage are retained
locally for auditability.

The optional terminal is a trusted-human convenience, **not a sandbox**. Never expose
this local build directly to a network or untrusted users. Read [SECURITY.md](SECURITY.md)
for the threat model, data-egress notes, and controls required before any remote or
multi-user deployment.

---

## Troubleshooting

- **Port already in use** — a previous `make dev` didn't shut down. Find and kill it:
  `lsof -ti :8000 | xargs kill` (and `:5173`).
- **`uv: command not found`** — the installer put it in `~/.local/bin`. Restart your
  shell, or `source $HOME/.local/bin/env`.
- **Terminal and Checks say “host tools locked”** — this is the secure default. Set
  `ENABLE_HOST_EXECUTION=true` in `backend/.env` and restart only if you intend to run
  trusted local commands. The terminal talks over `ws://127.0.0.1:8000/pty/...` and
  reaps its complete process group on disconnect.
- **An approved headless job still will not run** — confirm both execution switches,
  an active recorded workspace, and an absolute executable path. The executable must
  exist, be executable, and not be world-writable. Approval alone never unlocks M9.
- **Workspace creation says Git/Xcode is unavailable (macOS)** — run
  `sudo xcodebuild -license` in your own Terminal, review and accept Apple's license,
  then retry. Lemma does not accept system licenses on your behalf.
- **WebSocket won't connect** — confirm the backend is up
  (`curl http://127.0.0.1:8000/health`) and that no proxy/VPN blocks `ws://localhost`.
  The status-bar dot shows amber while reconnecting, green when connected.
- **Blank page or “Studio data is unavailable”** — hard-refresh once after upgrading,
  then confirm both servers are alive. `command -v uv` must print a path and
  `curl http://127.0.0.1:8000/health` must return JSON. The launcher now stops with a
  clear error instead of leaving the frontend running when its backend has exited.
- **The `[vite] failed to connect to websocket` console error** is Vite's own dev-server
  HMR socket, not this app — harmless.
- **Real models fail with a 401/auth error** — you set `MOCK_LLM=false` without a valid
  key for the model in `config.toml`. Add the key to `backend/.env` or set `MOCK_LLM=true`.
- **Reset local state** — after backing up anything you need, remove the specific
  `backend/data/app.db` file (recreated on next start). Workspace folders are separate
  under `~/ai-company-workspaces/`; review them individually before removing them.

---

## Layout

See [`PROMPT.md`](PROMPT.md) §5 for the full tree, or [`ARCHITECTURE.md`](ARCHITECTURE.md)
for the runtime picture. Top level: `backend/` (FastAPI), `frontend/` (Vite + React),
`learning/` (your retyping scratch space), `scripts/` (dev helpers).

---

## License

[MIT](LICENSE) © 2026 Danyal-0-1

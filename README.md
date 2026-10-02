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
project dossiers, model comparisons, per-project policies, retryable run history,
reusable templates, and a compact protocol → sources → evidence → review → capsule
assurance pipeline. The whole research path is demoable in mock mode with no keys or
cost. Optional headless coding remains disabled unless the operator crosses every
separate approval and configuration gate.

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.12+ | backend |
| [uv](https://docs.astral.sh/uv/) | latest | fast Python package/venv manager |
| Node | 20.19+ or 22.12+ | frontend (Vite) |
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
workflow. Installed builds also provide `lemma verify-capsule FILE` for offline
research-capsule integrity checks. The build requires pre-populated npm and uv caches.
See the
[`linux_install` guide](linux_install/README.md) for prerequisites, portable and
Debian installation, signing and verification, upgrades, data locations, security
notes, and limitations. The [Linux release workflow](.github/workflows/linux-release.yml)
builds both formats on Ubuntu, performs portable and Debian install round trips, and
smoke-tests the installed offline capsule verifier on every pull request and `main` push.

---

## R&D Studio walkthrough (mock mode, ~5 minutes)

1. Open **Organization** from the activity rail and create a department or mission
   team.
2. Add two or three agents. Give each one a role, mission, duties, the issues it must
   consider, ranked priorities, and a communication scope. These fields form its Duty
   Card; they do not grant tools or machine permissions.
3. Open **Research**, create a project and task, then define and approve the research
   protocol before the run. The compact assurance card always shows the next gate.
4. Open **Knowledge** to import a human-selected PDF/text file (or capture a note),
   preserve its checksums and exact excerpts, and link it into the task's bounded source
   packet. Return to **Research** and run the task under the approved protocol.
5. Review the finding in **Knowledge**, record each material claim, attach supporting,
   contradicting, or contextual evidence, and correct links or retire superseded claims.
   Once every finding is accepted and every active claim has intact task-linked support
   with no unresolved contradiction, accept it in **Research** and export the offline-
   verifiable capsule.
6. Open **Meetings**, choose a project, facilitator, and permitted participants, and
   write an agenda. Running the room collects one bounded contribution per participant
   and then asks the facilitator for a synthesis. Record the human outcome and action
   items, then promote an action into a traceable research task.
7. Use **Evaluations** for a bounded side-by-side model comparison and human scoring.
   Use **Operations** to inspect/cancel/retry attempts, set model allowlists and
   cumulative budgets, and create or instantiate reusable templates.
8. Use **HQ** for the organization overview and **Security** for capability boundaries.
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

Lemma makes the route explicit; it never treats a chat subscription as an API key or
silently falls back between them.

| Connection shown in Settings | Authentication | Billing / data path |
|---|---|---|
| OpenAI, Anthropic, Gemini, or DeepSeek **API** | key in `backend/.env` | separately metered provider API; remote egress |
| ChatGPT, Claude, or Google AI **account plan** | existing login in the official Codex, Claude Code, or Gemini CLI | eligible plan allowance; remote egress; no API-key fallback |
| **Ollama local** | none | loopback-only runtime; no provider billing |
| **Custom OpenAI-compatible** | optional key | determined by that server's operator; local or remote |

To connect one:

1. Copy the relevant variables from `backend/.env.example` into `backend/.env`.
   For an API route, add its key. For Ollama, list exact `ollama/...` model IDs. For a
   custom endpoint, provide its URL and `openai/...` model IDs.
2. For an account-plan route, install the official CLI and sign in from your normal
   terminal first: `codex login`, `claude auth login`, or run `gemini` and choose
   **Sign in with Google**. If `command -v codex`, `claude`, or `gemini` cannot find it,
   set the corresponding `LEMMA_*_EXECUTABLE` to its absolute path.
3. Set `MOCK_LLM=false`, restart `make dev`, then open **Settings → Models**. Each card
   identifies its auth mode, billing boundary, egress, and readiness. **Test
   connection** makes one real small request and may consume API credit or plan usage.
4. Open **Organization → New agent** and choose the connection and model on the duty
   card. The agent stores both values; every task run records the actual route's
   redacted fingerprint alongside the exact model and prompts.
5. In **Operations → Policy**, explicitly classify remote work. **Confidential** needs
   an allowlist; **local_only** accepts only mock mode or exact IDs in
   `LEMMA_LOCAL_MODEL_IDS`. A name such as `ollama/...` alone does not prove locality.

`MOCK_LLM=true` remains a global safe override: research runs use the local mock even
when a duty card names a live route, and provenance records that the mock actually ran.
The account-plan adapters run in an empty temporary directory with tools/customization
disabled and bounded input, output, and wall time. Unlike normal API requests, their
vendor CLIs do not offer a provider-side `max_output_tokens` guarantee, so plan usage
is only known after the process returns. Direct **Sign in with ChatGPT** OAuth is a
separate registered integration; this repository currently uses the installed Codex
CLI's account session instead.

### ⚠️ The billing warning (read this once)

Do not export provider API keys into the shell where you sign in to an account-plan
CLI. An ambient key can select API authentication and metered API billing instead of
the account session you intended. This app:

- keeps API keys in `backend/.env` (loaded into the backend process only and passed
  directly to the selected API request), and
- constructs a minimal child-process environment instead of copying the backend's
  environment. Provider keys, cloud tokens, credential variables, and agent sockets
  stay out of the embedded terminal, checks runner, and account-plan CLI adapters.

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
and kills the process group on cancellation or shutdown. Because this external process
can transmit workspace or project context independently of the research-model policy,
project-scoped headless automation is allowed only for projects explicitly classified
as **Public**.

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

- **Port already in use** — the launcher now reports the exact listener before starting
  either server. Inspect it with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, stop the displayed
  PID with `kill <PID>`, and wait a moment. If that same PID ignores `TERM`, use
  `kill -KILL <PID>` once, then confirm the `lsof` command returns nothing. Repeat with
  port `5173` only when Vite is also already running.
- **`uv: command not found`** — the installer put it in `~/.local/bin`. Restart your
  shell, or `source $HOME/.local/bin/env`.
- **Terminal and Checks say “host tools locked”** — this is the secure default. Stop
  `make dev`, set `ENABLE_HOST_EXECUTION=true` in `backend/.env`, and start `make dev`
  again only if you intend to run trusted local commands. Create or select an active
  Workbench workspace before opening Terminal. The panel now reports connection/start
  failures and offers **Retry**; its shell is resolved from executable bash/zsh paths
  on both macOS and Linux and its complete process group is reaped on disconnect.
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
- **A model route fails** — open **Settings → Models** and read that route's setup and
  status. API routes need the matching key, account-plan routes need an authenticated
  official CLI visible to the backend, Ollama must be running on the configured
  loopback URL, and custom endpoints must be reachable. Test the exact route/model;
  upstream details stay in backend logs rather than being exposed to the browser.
- **A real research run is blocked by project policy** — `local_only` deliberately
  rejects remote egress. For a verified on-device endpoint, add its exact configured
  model ID to `LEMMA_LOCAL_MODEL_IDS`; otherwise explicitly choose **Confidential** with
  an allowlist or **Public** in **Operations → Policy**.
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

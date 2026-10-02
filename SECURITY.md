# Lemma security model

Lemma is a local-first research workspace. It coordinates language models and can,
when explicitly enabled, expose a terminal and verification commands. Those are two
very different trust levels, so the platform keeps them separate.

## Safe default

- The backend is supported on `127.0.0.1` only.
- Research agents receive prompts and selected meeting context only. They have no
  filesystem, shell, network-tool, connector, or secret capability.
- Host command execution is disabled by default. Set `ENABLE_HOST_EXECUTION=true`
  only when you want to use the human-operated terminal and checks workbench.
- Optional headless coding has an independent off-by-default switch. Enabling the
  terminal does not enable automation, and approving a plan does not bypass either
  runtime switch or executable/workspace validation.
- Mock mode is enabled by default, so a fresh install sends no research to an
  external model provider and incurs no model cost.
- Agent communication is explicit and bounded. An agent may be isolated, restricted
  to its department, or allowed across the organization. Meetings have a fixed
  participant list and terminate after one contribution per participant plus a
  synthesis step.

Natural-language instructions never grant capabilities. A role description that says
"use the terminal" does not give an agent a terminal.

## The host-execution boundary

The embedded terminal is a convenience for a trusted human. It is **not a sandbox**.
When enabled, commands run as the operating-system user and may be able to access
files outside a project through normal OS permissions. Verification checks are also
real local processes, although Lemma constrains their environment, duration, output,
and process lifetime.

Do not enable host execution for untrusted users or expose this server to a network.
Production multi-user or remote deployment requires an isolated execution worker
(rootless container or microVM), authentication, TLS, per-project authorization,
resource quotas, and an audited network proxy. The current local application does
not claim to provide those controls.

### Optional headless automation

M9 is deliberately a second trust boundary. It accepts only a persisted, explicitly
approved plan for an active Lemma workspace and the audited Claude adapter. The
executable must be an absolute, existing, executable, non-world-writable file. Lemma
uses a fixed argument vector (no shell expansion), the shared credential-stripped
environment, workspace-root validation, timeout and output caps, durable status, and
process-group termination on cancellation or shutdown.

Those controls reduce accidental scope; they do not turn the external CLI into a
sandbox. It still runs as your operating-system user and may have access that is not
expressed by the plan. The recorded `read_workspace`, `write_workspace`, and
`run_checks` capabilities are human approval/audit intent, not kernel-enforced
filesystem or network policy. Review the plan and CLI billing/account state, inspect
the resulting diff, and keep M9 disabled for untrusted requests or workspaces.
Project-scoped headless execution additionally requires the project's data
classification to be `public`; local-only and confidential project plans fail closed.

## Browser boundary

The backend accepts only the local development UI origins and trusted loopback Host
headers. Unsafe cross-origin API requests and WebSocket connections are rejected.
The frontend is also served with deny-framing and a local content security policy to
resist clickjacking and unexpected remote resource loads. This protects the local
service from ordinary browser-based cross-site attacks; it is not a defense against
another process already running as the same OS user.

## Secrets and model egress

- Provider credentials belong in `backend/.env` during development or
  `${XDG_CONFIG_HOME:-~/.config}/lemma/.env` in an installed Linux build. Both are
  outside release payloads; the installed file is created with mode `0600`.
- Model routes are explicit and separately labeled as API key, account plan, local
  runtime, or custom endpoint. API keys are passed directly to only the selected
  LiteLLM request; they are not copied into process-wide environment variables,
  browser storage, agent rows, run snapshots, logs, or model-connection responses.
- Account-plan routes use an already authenticated official CLI and never fall back to
  an API key. The adapter starts a fixed executable without a shell, strips credential
  variables, uses an empty temporary working directory, disables user/project
  customization and known tool surfaces, and bounds prompt bytes, captured output,
  wall time, and process lifetime. CLI plan usage is remote egress. Vendor CLIs do not
  expose a reliable provider-side output-token ceiling, and CLI updates can change
  their flags; re-test after upgrades. Direct registered OAuth is preferable when a
  provider offers an appropriate tool-free integration.
- Ollama URLs are restricted to loopback. Custom OpenAI-compatible endpoints must use
  HTTPS unless they are loopback; their operator controls billing, retention, and
  downstream routing. An endpoint or model name is not proof that inference stays on
  this machine.
- Terminal and check processes receive a minimal allowlisted environment without
  provider keys, cloud tokens, credential variables, or agent sockets. Bounded Git
  processes use the same clean base; a separately confirmed push may add only a
  verified local SSH-agent socket or the fixed GitHub CLI credential helper. Git also
  ignores system/global executable config.
- Source Control reads are path-confined and output-bounded. Git mutations share the
  host-execution gate; pushes require a separate confirmation and are restricted to
  the current branch's one configured HTTPS or SSH upstream. Force pushes, hooks,
  external diff drivers, embedded URL credentials, and interactive prompts are denied.
- Research prompts can be sent to the configured model provider when mock mode is
  disabled. Task briefs plus the bounded contents of explicitly linked captured
  sources, and meeting context, may be included. Do not capture or link confidential
  data unless that provider and model are approved for it.
- Project policies enforce model allowlists, cumulative per-run token/cost limits,
  project spend ceilings, concurrency, and classification-aware model egress at run
  preflight and again immediately before each provider call. `local_only` permits only
  mock execution or model IDs the operator has
  explicitly attested in `LEMMA_LOCAL_MODEL_IDS`; `confidential` requires a nonempty
  project model allowlist. Model IDs are operator assertions, not network isolation.
  These are local guardrails, not a provider-side billing cap; provider usage can be
  reported only after a call completes, and pricing configuration must remain current.
- Each agent stores a connection ID and model ID separately. New task runs freeze the
  actual execution connection (including a truthful mock override) as a redacted target
  fingerprint, and each model-call record binds that snapshot to its prompts, model,
  usage, and integrity hash. This supports audit/tamper detection without preserving a
  credential or private executable/endpoint path.
- Model output is a synthesis, not verified evidence. The current secure research
  agents do not browse the web automatically. Lemma's assurance gate can require a
  pre-run approved protocol, task-scoped sources, hash-checked excerpts, supported and
  non-contradicted claims, and accepted human reviews, but people remain responsible
  for source quality and conclusions before relying on or publishing them.

## Stored data

Departments, agent duty cards, captured source bodies/excerpts, claims, frozen research
protocols and acceptance snapshots, task briefs, meeting transcripts/outcomes,
findings, exact model prompts, policy snapshots, evaluation responses/scores,
automation plans/output, paths, and cost records are
stored in the local SQLite database under `backend/data/` during
development or `${XDG_DATA_HOME:-~/.local/share}/lemma/data/` in an installed Linux
build. Configuration, data, operational state, versioned source copies, and project
workspaces have separate XDG or home-directory lifecycles; normal package upgrades and
removal preserve them.

Lemma also writes a deterministic projection of durable records to the **local Git
state vault** below the same data directory. It removes credential-shaped fields and
machine-specific absolute workspace paths, configures no remote, and never pushes
automatically. It is not a credential store or an encrypted backup: prompts, findings,
and meeting content remain readable and may be confidential. Protect or remove both the
SQLite database and state-vault history when erasing local research. Do not put
credentials in agent instructions, task briefs, or meeting agendas.

The local FTS5 table is a derived index of project, task, finding, source, claim, and
meeting text. Rebuilding or deleting the index does not erase canonical content; erase
the database, backups, and state-vault history when the underlying research must be
removed. Exported dossiers and research capsules are ordinary readable files and
require the same care.

Pending schema migrations automatically create a consistent database snapshot under
the data directory's private `backups/` folder. Manual backups use the same SQLite
online-backup path and include integrity checks plus a SHA-256 metadata sidecar; restore
refuses a missing or mismatched sidecar and cannot run while the backend holds the
database lock. Checksums detect corruption, not a malicious rewrite of both files, and
the backups are not encrypted. Protect, retain, and erase them like the live database.

## Linux release integrity

The offline Linux builder excludes `.env`, the live database, credential-shaped source
files, and private-key material. Each bundle has a complete SHA-256 manifest, and the
portable archive and Debian package have separate checksum files. The portable installer
and Debian packager both verify that manifest before accepting a bundle. A deterministic
CycloneDX SBOM generated from the locked JavaScript and production Python dependencies is
covered by the manifest and validated during installation/packaging.

These hashes detect corruption or modification but do **not** authenticate an unsigned
release. Release operators may optionally create detached minisign signatures for the
bundle manifest, portable archive, and local Debian package. Consumers must supply a
public key obtained through an independent trusted channel to make verification
mandatory; a key delivered only beside an untrusted artifact is not a trust root. A
release also contains architecture- and exact Python-minor-specific native dependencies,
so a mismatched interpreter is rejected. Packaging does not widen the deployment
boundary: installed services still bind only to loopback and remain intended for one
trusted operating-system user.

The installed `lemma verify-capsule FILE` command verifies a research capsule without
network access, provider credentials, or the live database. Its SHA-256 envelope and
referential checks detect corruption and inconsistent records; they are not a digital
signature and cannot establish that an untrusted author reported truthful research.

## Recommended deployment controls

Before adapting Lemma for a shared or remotely reachable installation, add all of:

1. Same-origin HTTPS with authenticated sessions and CSRF protection.
2. Organization/project authorization on every record and event subscription.
3. Durable, scoped event replay rather than a process-local broadcast bus.
4. Rootless disposable workers with workspace-only mounts, no host home or sockets,
   network denied by default, and CPU/memory/PID/disk/time/output quotas.
5. Short-lived capability grants for tools and secrets, plus human approval for
   external writes, publication, destructive changes, and expanded network access.
6. Encrypted backups, retention controls, security logs, and dependency scanning.

## Reporting a vulnerability

Do not include real credentials, private research, or exploit payloads in a public
issue. Contact the maintainer privately with the affected version, reproduction steps,
impact, and the smallest safe proof of concept.

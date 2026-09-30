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
  disabled. Do not paste confidential data unless that provider is approved for it.
- Model output is a synthesis, not verified evidence. The current secure research
  agents do not browse the web automatically. Validate important claims and sources
  before relying on or publishing them.

## Stored data

Departments, agent duty cards, tasks, meeting transcripts, findings, paths, and model
cost records are stored in the local SQLite database under `backend/data/` during
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

## Linux release integrity

The offline Linux builder excludes `.env`, the live database, credential-shaped source
files, and private-key material. Each bundle has a complete SHA-256 manifest, and the
portable archive and Debian package have separate checksum files. The portable installer
and Debian packager both verify that manifest before accepting a bundle.

These hashes detect corruption or modification but do **not** authenticate a release;
the project does not currently sign archives or Debian packages. Obtain artifacts and
checksums through a trusted channel. A release also contains architecture- and exact
Python-minor-specific native dependencies, so a mismatched interpreter is rejected.
Packaging does not widen the deployment boundary: installed services still bind only
to loopback and remain intended for one trusted operating-system user.

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

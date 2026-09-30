# Lemma on Linux

This directory builds and installs Lemma as a local, single-user Linux desktop
application. A release contains the production frontend, the backend source, and
its Python dependencies; Node and `uv` are build-time tools and are not needed to
run an installed release.

Two installation formats use the same release payload:

- the **portable installer** installs without root access and integrates with the
  current user's desktop and, when available, user-level systemd;
- the **Debian package** installs the application payload system-wide under
  `/opt/lemma`, while configuration, research data, and workspaces remain per-user.

Both formats serve the UI at <http://127.0.0.1:5173> and the API at
`127.0.0.1:8000`. They do not support network-facing operation.

## Prerequisites

### Build host

Build releases on Linux, not macOS or Windows. The host needs:

- an `x86_64` or `aarch64` Linux system;
- Bash 4.3 or newer and standard GNU core utilities;
- Python 3.12 or newer, including the exact minor version that target machines
  will use;
- Node.js 20 or newer and `npm`;
- `uv`, Git, GNU `tar`, `gzip`, `sha256sum`, `find`, `sort`, and `install`;
- all packages referenced by `frontend/package-lock.json` and `backend/uv.lock`
  already present in the local npm and uv caches.

The build deliberately runs package installation in offline mode. On a connected
preparation machine with the same operating system, CPU architecture, and Python
minor version, populate the caches once:

```bash
(cd frontend && npm ci --ignore-scripts --no-audit --no-fund)
(cd backend && uv sync --frozen)
```

Then transfer the repository and populated caches to the isolated builder if they
are different machines. Cache layout and transfer are package-manager details;
avoid copying a cache between operating systems or architectures.

Build on the oldest Linux distribution and Python minor version you intend to
support. The archive includes native Python wheels, but it does not include a
Python interpreter or system libraries such as glibc.

### Runtime host

An installed release needs:

- the same CPU architecture and exact Python `major.minor` recorded in
  `PYTHON_ABI` inside the release;
- Bash 4.3 or newer, Git, `flock` (normally from `util-linux`), and `sha256sum`;
- a graphical browser; `xdg-open` or `gio` enables automatic browser launch.

OpenSSH and the GitHub CLI are optional. They are useful for SSH Git remotes and
GitHub authentication, respectively. Run `lemma doctor` after installation to
check the host.

## Build an offline release

From the repository root:

```bash
./linux_install/build.sh
```

The build uses only the npm and uv caches and writes these architecture-specific
artifacts under `linux_install/dist/`:

```text
lemma-<version>-linux-<arch>/
lemma-<version>-linux-<arch>.tar.gz
lemma-<version>-linux-<arch>.tar.gz.sha256
```

The directory is directly installable. The archive is the portable release to
transfer. Each bundle carries top-level `install.sh`, `uninstall.sh`, `BUILD_INFO`,
`PYTHON_ABI`, and a complete `manifest.sha256`; third-party notices live below
`share/doc/lemma-linux/`. Verify the archive before extraction:

```bash
cd linux_install/dist
sha256sum --check lemma-<version>-linux-<arch>.tar.gz.sha256
```

Useful build options are:

```bash
./linux_install/build.sh --output /absolute/output/directory
./linux_install/build.sh --keep-work
./linux_install/build.sh --help
```

The builder refuses to overwrite an existing release. Remove or relocate an old
artifact deliberately before rebuilding. `SOURCE_DATE_EPOCH` may be set to control
archive timestamps; otherwise the most recent commit time is used.

## Portable installation

Extract a transferred archive and run the installer shipped at its root:

```bash
tar -xzf lemma-<version>-linux-<arch>.tar.gz
BUNDLE=./lemma-<version>-linux-<arch>
"$BUNDLE/install.sh" --bundle "$BUNDLE"
```

The default is a per-user installation and does not require `sudo`. Ensure
`~/.local/bin` is on `PATH`, then start Lemma. The default payload location is
`~/.local/opt/lemma`; launchers go in `~/.local/bin`, and desktop and user-systemd
integration follow the XDG directories.

```bash
lemma doctor
lemma open
```

The installer verifies the complete bundle manifest, rejects links, special files,
and privileged mode bits, and confirms the host architecture and exact Python ABI
before changing the installation. Set `LEMMA_PYTHON` to an exact interpreter path
when it is not discoverable on `PATH`. An upgrade may replace only an empty prefix
or one carrying the installer's receipt; it refuses unmanaged files and conflicting
integration paths. Use `--prefix` to choose another safe absolute location, or
`--system` as root for an administrator-managed install under `/opt/lemma` with
`/usr/local` integration.
Do not mix that layout with the Debian package. See every option with:

```bash
./linux_install/install.sh --help
```

To uninstall the portable application, use the matching uninstall script rather
than deleting individual desktop or service files:

```bash
./linux_install/uninstall.sh
```

The uninstaller remains at the installed prefix. For the default user install, run:

```bash
~/.local/opt/lemma/uninstall.sh
```

Pass the same `--prefix` and scope used during installation when they were not the
defaults. A system-scope uninstall requires root and rejects every `--purge` option.

Uninstallation removes installed program files and desktop/service integration.
It does not remove the user's configuration, database, versioned source worktrees,
logs, or project workspaces by default. After backing them up, request individual
categories explicitly; repeat `--purge` when more than one is intended:

```bash
./linux_install/uninstall.sh --purge config --purge state
```

Valid purge targets are `config`, `data`, `state`, and `workspaces`. Read
`./linux_install/uninstall.sh --help` and stop Lemma before requesting data removal.

## Debian package

First build the portable directory, then wrap that verified payload in a `.deb`:

```bash
./linux_install/build.sh
./linux_install/build-deb.sh --bundle \
  ./linux_install/dist/lemma-<version>-linux-<arch>
```

This step runs only on Linux and additionally needs `dpkg-deb` plus standard GNU
coreutils, findutils, `grep`, `sed`, and `awk`. It writes the package and its
checksum to `linux_install/dist/` by default:

```text
lemma_<debian-version>_<amd64|arm64>.deb
lemma_<debian-version>_<amd64|arm64>.deb.sha256
```

Use `--output DIRECTORY` to choose another destination or `--keep-work` to retain
the temporary package tree for inspection. Verify and install the resulting local
package with APT so Debian can check its runtime dependencies, including the exact
versioned Python interpreter package:

```bash
(cd linux_install/dist && \
  sha256sum --check lemma_<debian-version>_<deb-arch>.deb.sha256)
sudo apt install /absolute/path/to/lemma_<debian-version>_<deb-arch>.deb
lemma doctor
lemma open
```

Upgrade by stopping Lemma, installing the newer `.deb` the same way, then running
`lemma restart`. The package installs a user unit but deliberately has no maintainer
scripts that start, stop, or restart processes in user sessions. Remove only the
packaged application with:

```bash
lemma stop
sudo apt remove lemma
```

Package removal intentionally leaves each user's files listed below. Review and
delete those files as that user only when their research history and workspaces are
no longer needed. `dpkg -i` can install the package directly, but APT is preferred
because it reports or resolves missing dependencies.

## Runtime commands

The `lemma` launcher controls either installation format:

```text
lemma open       start if needed and open the browser (default)
lemma start      start without opening a browser
lemma stop       stop the service
lemma restart    stop and start the service
lemma status     report service and backend health
lemma logs       follow the journal or fallback log
lemma config     print the private configuration-file path
lemma doctor     verify files and runtime prerequisites
lemma help       show launcher help
```

When a user-level systemd unit is installed, the launcher delegates to it.
Otherwise the portable launcher runs a private background process and keeps its PID
and lock below the runtime directory.

## Configuration and stored data

Lemma follows the XDG base-directory variables when set. Defaults are:

| Purpose | Default location |
|---|---|
| Private configuration and provider keys | `~/.config/lemma/.env` |
| SQLite database | `~/.local/share/lemma/data/app.db` |
| Local Git state vault | `~/.local/share/lemma/data/git-vault/` |
| Versioned, user-writable application source | `~/.local/share/lemma/app-<version>/` |
| Fallback service log | `~/.local/state/lemma/server.log` |
| PID and process lock | `$XDG_RUNTIME_DIR/lemma-server.{pid,lock}` or `/tmp/lemma-runtime-$UID/` |
| User-created project repositories | `~/ai-company-workspaces/` |

The configuration is created on first start from `assets/env.default` with mode
`0600`. Mock-model mode is on and host execution is off by default. Use
`lemma config` to locate the active file. Set provider credentials there only when
you intentionally set `MOCK_LLM=false`; set `ENABLE_HOST_EXECUTION=true` only when
you intend to enable the human-operated terminal and checks.

`WORKSPACES_DIR` can relocate newly created project repositories. Existing
repositories are not moved automatically. The SQLite database contains research
projects, prompts, findings, meeting transcripts, local paths, and cost records;
back it up together with any workspaces you need to preserve. The uninstaller's
`--purge workspaces` target covers the recorded default directory only; review a
custom `WORKSPACES_DIR` separately.

The state vault is a deterministic, reviewable Git snapshot of durable application
records, not a credential store. Lemma removes credential-shaped fields and absolute
workspace paths, configures no remote, and never pushes it automatically. It still
contains prompts, findings, and meeting content, so protect and back it up as sensitive
research data.

## Security notes

- Verify the archive checksum and the internal `manifest.sha256` before trusting a
  transferred release. Checksums detect changes; they do not authenticate an
  unsigned release, so obtain artifacts through a trusted channel.
- The backend and static frontend always bind to loopback. Do not place this build
  behind a network proxy or expose it to other users.
- Provider keys live only in the private `.env` file. The service starts from a
  minimal environment, and terminal/check child processes do not inherit provider
  keys, cloud credentials, or agent sockets.
- Mock mode sends no prompts to a model provider. With mock mode disabled, selected
  prompts and context leave the machine for the configured provider.
- Host execution is disabled by default. When enabled, the terminal runs with the
  current operating-system user's permissions and is **not a sandbox**.
- The systemd user unit adds process hardening, but it is not an isolation boundary
  for deliberately enabled host commands.

See [`../SECURITY.md`](../SECURITY.md) for the full threat model.

## Upgrades and backups

Give every changed release a new application version in `frontend/package.json`,
`backend/pyproject.toml`, and `backend/app/main.py`; the builder refuses disagreement.
Do not publish different code under an existing version. The writable backend source
tree is intentionally keyed as `app-<version>`, so reusing a version would preserve
that earlier source tree instead of seeding the changed backend.

1. Back up `~/.config/lemma/`, `~/.local/share/lemma/data/`, and any project
   workspaces that matter.
2. Build or obtain a release for the machine's architecture and exact Python minor
   version, and verify its checksum.
3. Stop the running service with `lemma stop`.
4. Run the portable installer again, or install the newer `.deb` with APT.
5. Run `lemma doctor`, then `lemma start` and `lemma status`.

Application payloads are replaceable; configuration, the database, and workspaces
live outside them and survive normal upgrades and package removal. On first launch,
each version creates its own Git-tracked user-writable source worktree. Old
`app-<version>` directories may be reviewed and removed after a successful upgrade,
but never remove the shared `data/` directory as part of that cleanup.

The project does not currently promise downgrade-safe database migrations. Keep a
database backup before upgrading, and do not open a database written by a newer
release with an older release unless that path has been tested.

## Current limitations

- Releases are Linux-only and support `x86_64` and `aarch64` only.
- A release is tied to its build architecture, Python minor version, and compatible
  system C libraries. Build on the oldest target distribution.
- Python itself is not bundled. Node, npm, and `uv` are not runtime requirements.
- Ports 5173 and 8000 are fixed and must be available.
- This is a local, single-user application with no remote authentication or
  multi-user authorization.
- There are no RPM, Flatpak, Snap, or AppImage artifacts in this pipeline.
- Offline means dependency resolution and installation make no network requests;
  it does not make the overall toolchain hermetic or guarantee byte-identical native
  wheels across different builders.
- Release archives and local Debian packages are checksummed but not currently
  cryptographically signed.

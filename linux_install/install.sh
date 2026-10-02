#!/usr/bin/env bash
# Install a verified Lemma Linux bundle without mixing it with mutable user data.
set -euo pipefail
umask 022

PROGRAM_NAME="${0##*/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BUNDLE=""
PREFIX=""
SCOPE="user"
SCOPE_SET=0
VERIFY_KEY=""

usage() {
  cat <<'EOF'
Usage: install.sh --bundle DIRECTORY [OPTIONS]

Install an unpacked Lemma Linux bundle. The default is a per-user install:

  application root   ~/.local/opt/lemma
  command links       ~/.local/bin
  desktop files       ${XDG_DATA_HOME:-~/.local/share}
  user service        ${XDG_DATA_HOME:-~/.local/share}/systemd/user

Options:
  --bundle DIRECTORY  Unpacked bundle made by build.sh (required unless this
                      script itself is in a bundle root)
  --prefix DIRECTORY  Isolated application root; never a general prefix such
                      as /usr/local (default: ~/.local/opt/lemma for --user,
                      /opt/lemma for --system)
  --user              Install for the current user (default)
  --system            Install system-wide; requires root
  --minisign-public-key FILE
                      Require and verify manifest.sha256.minisig with this
                      independently trusted minisign public-key file
  -h, --help          Show this help

The installer verifies manifest.sha256, refuses symbolic links and special
files in the bundle, and will not replace unrelated desktop or command files.
It does not create or modify Lemma's private configuration or application data.
EOF
}

die() {
  printf '%s: ERROR: %s\n' "$PROGRAM_NAME" "$*" >&2
  exit 1
}

warn() {
  printf '%s: warning: %s\n' "$PROGRAM_NAME" "$*" >&2
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "missing value for $1"
}

while (($#)); do
  case "$1" in
    --bundle)
      need_value "$@"
      BUNDLE="$2"
      shift 2
      ;;
    --bundle=*)
      BUNDLE="${1#*=}"
      [[ -n "$BUNDLE" ]] || die "missing value for --bundle"
      shift
      ;;
    --prefix)
      need_value "$@"
      PREFIX="$2"
      shift 2
      ;;
    --prefix=*)
      PREFIX="${1#*=}"
      [[ -n "$PREFIX" ]] || die "missing value for --prefix"
      shift
      ;;
    --user)
      [[ "$SCOPE_SET" -eq 0 || "$SCOPE" == "user" ]] || \
        die "--user and --system cannot be combined"
      SCOPE="user"
      SCOPE_SET=1
      shift
      ;;
    --system)
      [[ "$SCOPE_SET" -eq 0 || "$SCOPE" == "system" ]] || \
        die "--user and --system cannot be combined"
      SCOPE="system"
      SCOPE_SET=1
      shift
      ;;
    --minisign-public-key)
      need_value "$@"
      VERIFY_KEY="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      (($# == 0)) || die "unexpected positional argument: $1"
      ;;
    -*|*)
      die "unknown argument: $1 (try --help)"
      ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || die "this installer runs only on Linux"
((BASH_VERSINFO[0] > 4 || \
  (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 3))) || \
  die "Bash 4.3 or newer is required"

for command_name in chmod cp dirname find grep install ln mktemp mv readlink \
  realpath rm rmdir sed sha256sum sort stat tr; do
  command -v "$command_name" >/dev/null 2>&1 || \
    die "required command is unavailable: $command_name"
done
if [[ -n "$VERIFY_KEY" ]]; then
  command -v minisign >/dev/null 2>&1 || \
    die "minisign is required only when --minisign-public-key is used"
  [[ -f "$VERIFY_KEY" && ! -L "$VERIFY_KEY" ]] || \
    die "trusted minisign public key must be a regular, non-symbolic-link file"
  VERIFY_KEY="$(realpath -e -- "$VERIFY_KEY")"
fi

[[ -n "${HOME:-}" && "$HOME" == /* ]] || die "HOME must be an absolute path"
if [[ "$SCOPE" == "system" && "$EUID" -ne 0 ]]; then
  die "--system requires root; use the default --user install without sudo"
fi

normalize_path() {
  local raw_path="$1"
  local description="$2"
  [[ "$raw_path" == /* ]] || die "$description must be an absolute path: $raw_path"
  [[ "$raw_path" != *$'\n'* && "$raw_path" != *$'\r'* ]] || \
    die "$description contains a line break"
  realpath -m -- "$raw_path"
}

paths_overlap() {
  local first="$1"
  local second="$2"
  case "$first/" in
    "$second/"*) return 0 ;;
  esac
  case "$second/" in
    "$first/"*) return 0 ;;
  esac
  return 1
}

validate_install_root() {
  local candidate="$1"
  case "$candidate" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib32|/lib64|/media|/mnt|/opt|/proc|\
    /root|/run|/sbin|/srv|/sys|/tmp|/usr|/usr/local|/var|/var/tmp)
      die "refusing broad or system-critical install root: $candidate"
      ;;
  esac
  [[ "$candidate" =~ ^/[A-Za-z0-9._/+@=,:-]+$ ]] || \
    die "install root contains characters unsafe in desktop/service files: $candidate"
}

HOME_PATH="$(normalize_path "$HOME" "HOME")"
if [[ "$SCOPE" == "user" ]]; then
  DATA_HOME="$(normalize_path "${XDG_DATA_HOME:-$HOME/.local/share}" "XDG_DATA_HOME")"
  CONFIG_HOME="$(normalize_path "${XDG_CONFIG_HOME:-$HOME/.config}" "XDG_CONFIG_HOME")"
  STATE_HOME="$(normalize_path "${XDG_STATE_HOME:-$HOME/.local/state}" "XDG_STATE_HOME")"
  BIN_DIR="$(normalize_path "$HOME/.local/bin" "user command directory")"
  DEFAULT_PREFIX="$HOME/.local/opt/lemma"
  DESKTOP_FILE="$DATA_HOME/applications/io.lemma.Lemma.desktop"
  ICON_FILE="$DATA_HOME/icons/hicolor/scalable/apps/io.lemma.Lemma.svg"
  METAINFO_FILE="$DATA_HOME/metainfo/io.lemma.Lemma.metainfo.xml"
  UNIT_FILE="$DATA_HOME/systemd/user/lemma.service"
  CONFIG_PATH="$CONFIG_HOME/lemma"
  DATA_PATH="$DATA_HOME/lemma"
  STATE_PATH="$STATE_HOME/lemma"
  WORKSPACES_PATH="$HOME_PATH/ai-company-workspaces"
else
  BIN_DIR="/usr/local/bin"
  DEFAULT_PREFIX="/opt/lemma"
  DESKTOP_FILE="/usr/local/share/applications/io.lemma.Lemma.desktop"
  ICON_FILE="/usr/local/share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg"
  METAINFO_FILE="/usr/local/share/metainfo/io.lemma.Lemma.metainfo.xml"
  UNIT_FILE="/usr/local/lib/systemd/user/lemma.service"
  CONFIG_PATH=""
  DATA_PATH=""
  STATE_PATH=""
  WORKSPACES_PATH=""
fi

PREFIX="$(normalize_path "${PREFIX:-$DEFAULT_PREFIX}" "install root")"
validate_install_root "$PREFIX"

for unsafe_root in "$HOME_PATH" "$BIN_DIR"; do
  [[ "$PREFIX" != "$unsafe_root" ]] || die "refusing broad install root: $PREFIX"
done
if [[ "$SCOPE" == "user" ]]; then
  mutable_paths=("$CONFIG_PATH" "$DATA_PATH" "$STATE_PATH" "$WORKSPACES_PATH")
  for mutable_path in "${mutable_paths[@]}"; do
    if paths_overlap "$PREFIX" "$mutable_path"; then
      die "install root must be separate from mutable user data: $mutable_path"
    fi
  done
  for ((first_index = 0; first_index < ${#mutable_paths[@]}; first_index++)); do
    for ((second_index = first_index + 1; \
          second_index < ${#mutable_paths[@]}; second_index++)); do
      if paths_overlap "${mutable_paths[$first_index]}" \
        "${mutable_paths[$second_index]}"; then
        die "mutable user-data paths must not overlap: ${mutable_paths[$first_index]} and ${mutable_paths[$second_index]}"
      fi
    done
  done
fi

if [[ -z "$BUNDLE" ]]; then
  if [[ -f "$SCRIPT_DIR/VERSION" && -f "$SCRIPT_DIR/manifest.sha256" ]]; then
    BUNDLE="$SCRIPT_DIR"
  else
    die "--bundle DIRECTORY is required (see --help)"
  fi
fi
[[ -d "$BUNDLE" ]] || die "bundle directory does not exist: $BUNDLE"
BUNDLE="$(realpath -e -- "$BUNDLE")"

if paths_overlap "$PREFIX" "$BUNDLE"; then
  die "the bundle and install root must not contain one another"
fi
[[ "$SCRIPT_DIR" != "$PREFIX" ]] || \
  die "run install.sh from the new bundle, not from the existing install root"

if [[ -n "$(find "$BUNDLE" -mindepth 1 ! -type d ! -type f -print -quit)" ]]; then
  die "bundle contains a symbolic link or special file"
fi
if [[ -n "$(find "$BUNDLE" -mindepth 1 \( -type d -o -type f \) -perm /022 -print -quit)" ]]; then
  die "bundle contains a group- or world-writable path"
fi
if [[ -n "$(find "$BUNDLE" -mindepth 1 \( -type d -o -type f \) -perm /7000 -print -quit)" ]]; then
  die "bundle contains a setuid, setgid, or sticky path"
fi
for reserved_name in .lemma-install .lemma-install.next .lemma-install.previous; do
  [[ ! -e "$BUNDLE/$reserved_name" && ! -L "$BUNDLE/$reserved_name" ]] || \
    die "bundle contains reserved installer metadata: $reserved_name"
done

required_bundle_files=(
  VERSION
  PYTHON_ABI
  BUILD_INFO
  manifest.sha256
  install.sh
  uninstall.sh
  bin/lemma
  bin/lemma-server
  bin/lemma-doctor
  libexec/backend_runner.py
  libexec/frontend_server.py
  libexec/research_capsule_runner.py
  verify-release.sh
  share/doc/lemma-linux/SBOM.cdx.json
  share/doc/lemma-linux/THIRD_PARTY_NOTICES.md
  share/lemma/app/linux_install/sbom.py
  share/lemma/app/backend/alembic.ini
  share/lemma/app/backend/app/lab/assurance.py
  share/lemma/app/backend/app/lab/governance.py
  share/lemma/app/backend/app/lab/integrity.py
  share/lemma/app/backend/app/lab/research_capsule.py
  share/lemma/app/backend/app/lab/source_import.py
  share/lemma/app/backend/app/lab/source_routes.py
  share/lemma/app/backend/migrations/versions/0003_research_assurance.py
  share/lemma/app/backend/migrations/versions/0004_research_assurance_hardening.py
  share/lemma/app/backend/migrations/versions/0005_model_connections.py
  share/applications/io.lemma.Lemma.desktop.in
  share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg
  share/metainfo/io.lemma.Lemma.metainfo.xml
  share/systemd/user/lemma.service.in
  share/lemma/env.default
  share/lemma/web/index.html
)
for relative_path in "${required_bundle_files[@]}"; do
  [[ -f "$BUNDLE/$relative_path" ]] || \
    die "bundle is incomplete; missing $relative_path"
done
required_bundle_directories=(
  share/doc/lemma-linux/third-party/javascript
  share/lemma/app/backend/app
  share/lemma/app/backend/migrations/versions
  share/lemma/python
  share/lemma/web
)
for relative_path in "${required_bundle_directories[@]}"; do
  [[ -d "$BUNDLE/$relative_path" ]] || \
    die "bundle is incomplete; missing $relative_path"
done
for executable_path in install.sh uninstall.sh bin/lemma bin/lemma-server bin/lemma-doctor; do
  [[ -x "$BUNDLE/$executable_path" ]] || \
    die "bundle launcher is not executable: $executable_path"
done
[[ -x "$BUNDLE/verify-release.sh" ]] || \
  die "bundle launcher is not executable: verify-release.sh"

validate_relative_path() {
  local relative_path="$1"
  [[ -n "$relative_path" && "$relative_path" != /* ]] || return 1
  [[ "$relative_path" != "." && "$relative_path" != ".." ]] || return 1
  [[ "$relative_path" != ../* && "$relative_path" != */../* && \
     "$relative_path" != */.. ]] || return 1
  [[ "$relative_path" != *$'\n'* && "$relative_path" != *$'\r'* ]] || return 1
  # The vendored LiteLLM static UI uses '!' and '~' in generated asset names.
  [[ "$relative_path" =~ ^[A-Za-z0-9._/+@=,:!~-]+$ ]] || return 1
}

manifest_signature_count=0
if [[ -e "$BUNDLE/manifest.sha256.minisig" || \
      -L "$BUNDLE/manifest.sha256.minisig" ]]; then
  [[ -f "$BUNDLE/manifest.sha256.minisig" && \
     ! -L "$BUNDLE/manifest.sha256.minisig" ]] || \
    die "bundle manifest signature is not a regular file"
  manifest_signature_count=1
fi
if [[ -n "$VERIFY_KEY" ]]; then
  [[ "$manifest_signature_count" -eq 1 ]] || \
    die "--minisign-public-key requires manifest.sha256.minisig"
  minisign -V -q -p "$VERIFY_KEY" -m "$BUNDLE/manifest.sha256" \
    -x "$BUNDLE/manifest.sha256.minisig" || \
    die "bundle manifest signature verification failed"
elif [[ "$manifest_signature_count" -eq 1 ]]; then
  warn "bundle signature was not authenticated; use --minisign-public-key to require it"
fi

declare -A manifest_paths=()
manifest_count=0
while IFS= read -r checksum_line || [[ -n "$checksum_line" ]]; do
  [[ "$checksum_line" =~ ^[0-9a-f]{64}\ \ \./ ]] || \
    die "manifest.sha256 has an unsupported or unsafe entry"
  relative_path="${checksum_line:68}"
  # Bash's regex above consumes: 64 hex digits, two spaces, and './'.
  validate_relative_path "$relative_path" || \
    die "manifest.sha256 contains an unsafe path: $relative_path"
  [[ "$relative_path" != "manifest.sha256" && \
     "$relative_path" != "manifest.sha256.minisig" ]] || \
    die "the detached manifest and its signature must not list themselves"
  [[ -z "${manifest_paths[$relative_path]+present}" ]] || \
    die "manifest.sha256 contains a duplicate path: $relative_path"
  [[ -f "$BUNDLE/$relative_path" ]] || \
    die "manifest.sha256 names a missing file: $relative_path"
  manifest_paths["$relative_path"]=1
  manifest_count=$((manifest_count + 1))
done < "$BUNDLE/manifest.sha256"
((manifest_count > 0)) || die "manifest.sha256 is empty"

declare -A new_file_set=()
new_files=()
while IFS= read -r -d '' relative_path; do
  relative_path="${relative_path#./}"
  validate_relative_path "$relative_path" || \
    die "bundle contains an unsafe file name"
  new_file_set["$relative_path"]=1
  new_files+=("$relative_path")
  if [[ "$relative_path" != "manifest.sha256" && \
        "$relative_path" != "manifest.sha256.minisig" && \
        -z "${manifest_paths[$relative_path]+present}" ]]; then
    die "bundle file is not covered by manifest.sha256: $relative_path"
  fi
done < <(cd "$BUNDLE" && find . -mindepth 1 -type f -print0 | LC_ALL=C sort -z)

if ((${#new_files[@]} != manifest_count + 1 + manifest_signature_count)); then
  die "manifest.sha256 does not describe the complete bundle"
fi

new_dirs=()
while IFS= read -r -d '' relative_path; do
  relative_path="${relative_path#./}"
  validate_relative_path "$relative_path" || \
    die "bundle contains an unsafe directory name"
  new_dirs+=("$relative_path")
done < <(cd "$BUNDLE" && find . -mindepth 1 -depth -type d -print0)

if ! (cd "$BUNDLE" && sha256sum --check --strict --quiet manifest.sha256); then
  die "bundle checksum verification failed"
fi

mapfile -t version_lines < "$BUNDLE/VERSION"
[[ "${#version_lines[@]}" -eq 1 ]] || die "VERSION must contain exactly one line"
VERSION="${version_lines[0]}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)*$ ]] || \
  die "bundle has an invalid VERSION"

mapfile -t python_lines < "$BUNDLE/PYTHON_ABI"
[[ "${#python_lines[@]}" -eq 1 ]] || \
  die "PYTHON_ABI must contain exactly one line"
PYTHON_ABI="${python_lines[0]}"
[[ "$PYTHON_ABI" =~ ^3\.([0-9]+)$ ]] || \
  die "bundle has an invalid PYTHON_ABI"
python_minor="${BASH_REMATCH[1]}"
((10#$python_minor >= 12)) || die "Python 3.12 or newer is required"

case "$(uname -m)" in
  x86_64|amd64) host_arch="x86_64" ;;
  aarch64|arm64) host_arch="aarch64" ;;
  *) die "unsupported Linux architecture: $(uname -m)" ;;
esac

info_version=""
info_arch=""
info_python_abi=""
version_fields=0
arch_fields=0
python_fields=0
while IFS='=' read -r info_key info_value || [[ -n "$info_key$info_value" ]]; do
  case "$info_key" in
    version)
      version_fields=$((version_fields + 1))
      info_version="$info_value"
      ;;
    architecture)
      arch_fields=$((arch_fields + 1))
      info_arch="$info_value"
      ;;
    python_abi)
      python_fields=$((python_fields + 1))
      info_python_abi="$info_value"
      ;;
  esac
done < "$BUNDLE/BUILD_INFO"
[[ "$version_fields" -eq 1 && "$info_version" == "$VERSION" ]] || \
  die "BUILD_INFO version does not match VERSION"
[[ "$arch_fields" -eq 1 && "$info_arch" == "$host_arch" ]] || \
  die "bundle architecture ${info_arch:-unknown} does not match host $host_arch"
[[ "$python_fields" -eq 1 && "$info_python_abi" == "$PYTHON_ABI" ]] || \
  die "BUILD_INFO Python ABI does not match PYTHON_ABI"

if [[ -n "${LEMMA_PYTHON:-}" ]]; then
  PYTHON_BIN="$(command -v -- "$LEMMA_PYTHON" 2>/dev/null || true)"
else
  PYTHON_BIN="$(command -v "python$PYTHON_ABI" 2>/dev/null || \
    command -v python3 2>/dev/null || true)"
fi
[[ -n "$PYTHON_BIN" ]] || die "Python $PYTHON_ABI is required"
actual_python_abi="$($PYTHON_BIN -I -B -c \
  'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "$actual_python_abi" == "$PYTHON_ABI" ]] || \
  die "bundle requires Python $PYTHON_ABI, but $PYTHON_BIN is $actual_python_abi"
"$PYTHON_BIN" -I -B "$BUNDLE/share/lemma/app/linux_install/sbom.py" validate \
  "$BUNDLE/share/doc/lemma-linux/SBOM.cdx.json" \
  --application-version "$VERSION" || die "bundle SBOM validation failed"

MARKER="$PREFIX/.lemma-install"
NEXT_MARKER="$PREFIX/.lemma-install.next"
PREVIOUS_MARKER="$PREFIX/.lemma-install.previous"
receipt_files=(
  format scope prefix version installed-files installed-directories
  integration-paths config-path data-path state-path workspaces-path
)
old_files=()
old_dirs=()
old_integrations=()
declare -A old_file_set=()
declare -A old_dir_set=()
managed_install=0

read_owned_file() {
  local file_path="$1"
  [[ -f "$file_path" && ! -L "$file_path" ]] || \
    die "installation metadata is missing or unsafe: $file_path"
  [[ "$(stat -c '%u' -- "$file_path")" == "$EUID" ]] || \
    die "installation metadata is not owned by the installing user: $file_path"
  REPLY=""
  IFS= read -r REPLY < "$file_path" || true
}

cleanup_receipt_directory() {
  local receipt_directory="$1"
  local receipt_file
  local receipt_temp
  [[ -d "$receipt_directory" && ! -L "$receipt_directory" ]] || \
    die "staged installation receipt is unsafe: $receipt_directory"
  [[ "$(stat -c '%u' -- "$receipt_directory")" == "$EUID" ]] || \
    die "staged installation receipt is not owned by the installing user"
  for receipt_file in "${receipt_files[@]}"; do
    if [[ -e "$receipt_directory/$receipt_file" || \
          -L "$receipt_directory/$receipt_file" ]]; then
      [[ -f "$receipt_directory/$receipt_file" && \
         ! -L "$receipt_directory/$receipt_file" ]] || \
        die "staged installation receipt contains an unsafe path"
      [[ "$(stat -c '%u' -- "$receipt_directory/$receipt_file")" == "$EUID" ]] || \
        die "staged installation receipt contains a file owned by another user"
      rm -f -- "$receipt_directory/$receipt_file"
    fi
  done
  # A power loss may leave a securely-created render/atomic-write temporary from
  # an older installer invocation. Remove only our exact eight-character patterns.
  for receipt_temp in "$receipt_directory"/.desktop.???????? \
    "$receipt_directory"/.service.???????? \
    "$receipt_directory"/.integration-paths.????????; do
    [[ -e "$receipt_temp" || -L "$receipt_temp" ]] || continue
    [[ -f "$receipt_temp" && ! -L "$receipt_temp" ]] || \
      die "staged installation receipt contains an unsafe temporary path"
    [[ "$(stat -c '%u' -- "$receipt_temp")" == "$EUID" ]] || \
      die "staged installation receipt contains a temporary owned by another user"
    rm -f -- "$receipt_temp"
  done
  rmdir -- "$receipt_directory" 2>/dev/null || \
    die "staged installation receipt contains an unexpected path"
}

safe_integration_path() {
  local candidate="$1"
  [[ "$candidate" == /* && "$candidate" != *$'\n'* && \
     "$candidate" != *$'\r'* ]] || return 1
  case "${candidate##*/}" in
    lemma|lemma-server|lemma-doctor|io.lemma.Lemma.desktop|\
    io.lemma.Lemma.svg|io.lemma.Lemma.metainfo.xml|lemma.service)
      return 0
      ;;
  esac
  return 1
}

if [[ -L "$PREFIX" ]]; then
  die "install root must not be a symbolic link: $PREFIX"
elif [[ -e "$PREFIX" && ! -d "$PREFIX" ]]; then
  die "install root exists and is not a directory: $PREFIX"
elif [[ -d "$PREFIX" ]]; then
  [[ "$(stat -c '%u' -- "$PREFIX")" == "$EUID" ]] || \
    die "install root is not owned by the installing user: $PREFIX"
  [[ -z "$(find "$PREFIX" -type l -print -quit)" ]] || \
    die "existing install root contains a symbolic link; refusing to update"

  # Recover the only non-atomic gap in a receipt-directory exchange. The previous
  # receipt remains complete until the new one has taken the canonical name.
  if [[ ! -e "$MARKER" && \
        ( -e "$PREVIOUS_MARKER" || -L "$PREVIOUS_MARKER" ) ]]; then
    [[ -d "$PREVIOUS_MARKER" && ! -L "$PREVIOUS_MARKER" ]] || \
      die "previous installation receipt is unsafe"
    [[ "$(stat -c '%u' -- "$PREVIOUS_MARKER")" == "$EUID" ]] || \
      die "previous installation receipt is not owned by the installing user"
    mv -- "$PREVIOUS_MARKER" "$MARKER"
  fi
  if [[ -e "$NEXT_MARKER" || -L "$NEXT_MARKER" ]]; then
    cleanup_receipt_directory "$NEXT_MARKER"
  fi

  if [[ -e "$MARKER" ]]; then
    [[ -d "$MARKER" && ! -L "$MARKER" ]] || \
      die "installation marker is unsafe: $MARKER"
    read_owned_file "$MARKER/format"
    [[ "$REPLY" == "1" ]] || die "unsupported installation receipt format"
    read_owned_file "$MARKER/scope"
    [[ "$REPLY" == "$SCOPE" ]] || \
      die "existing installation uses --$REPLY; rerun with that scope"
    read_owned_file "$MARKER/prefix"
    [[ "$REPLY" == "$PREFIX" ]] || \
      die "installation was moved from its recorded prefix: $REPLY"

    for receipt_file in installed-files installed-directories integration-paths; do
      [[ -f "$MARKER/$receipt_file" && ! -L "$MARKER/$receipt_file" ]] || \
        die "installation receipt is incomplete: $receipt_file"
      [[ "$(stat -c '%u' -- "$MARKER/$receipt_file")" == "$EUID" ]] || \
        die "installation receipt is not owned by the installing user"
    done
    mapfile -t old_files < "$MARKER/installed-files"
    mapfile -t old_dirs < "$MARKER/installed-directories"
    mapfile -t old_integrations < "$MARKER/integration-paths"
    for relative_path in "${old_files[@]}"; do
      validate_relative_path "$relative_path" || \
        die "existing installation receipt contains an unsafe path"
      old_file_set["$relative_path"]=1
    done
    for relative_path in "${old_dirs[@]}"; do
      validate_relative_path "$relative_path" || \
        die "existing installation receipt contains an unsafe path"
      old_dir_set["$relative_path"]=1
    done
    for integration_path in "${old_integrations[@]}"; do
      safe_integration_path "$integration_path" || \
        die "existing installation receipt contains an unsafe integration path"
    done
    managed_install=1
    if [[ -e "$PREVIOUS_MARKER" || -L "$PREVIOUS_MARKER" ]]; then
      cleanup_receipt_directory "$PREVIOUS_MARKER"
    fi
  elif [[ -n "$(find "$PREFIX" -mindepth 1 -print -quit)" ]]; then
    die "install root is non-empty and was not created by Lemma: $PREFIX"
  fi
fi

desired_integrations=(
  "$BIN_DIR/lemma"
  "$BIN_DIR/lemma-server"
  "$BIN_DIR/lemma-doctor"
  "$DESKTOP_FILE"
  "$ICON_FILE"
  "$METAINFO_FILE"
  "$UNIT_FILE"
)
for integration_path in "${desired_integrations[@]}"; do
  if paths_overlap "$PREFIX" "$integration_path"; then
    die "install root must not overlap an integration path: $integration_path"
  fi
done

was_previous_integration() {
  local candidate="$1"
  local old_path
  for old_path in "${old_integrations[@]}"; do
    [[ "$candidate" == "$old_path" ]] && return 0
  done
  return 1
}

for integration_path in "${desired_integrations[@]}"; do
  if [[ -e "$integration_path" || -L "$integration_path" ]]; then
    [[ ! -d "$integration_path" || -L "$integration_path" ]] || \
      die "integration target is a directory: $integration_path"
    was_previous_integration "$integration_path" || \
      die "refusing to replace an unmanaged file: $integration_path"
  fi
done

# Do not overwrite an untracked path merely because a newer bundle happens to
# introduce the same name.
for relative_path in "${new_files[@]}"; do
  candidate_path="$PREFIX/$relative_path"
  if [[ -e "$candidate_path" || -L "$candidate_path" ]]; then
    if [[ -d "$candidate_path" && ! -L "$candidate_path" ]]; then
      [[ -n "${old_dir_set[$relative_path]+present}" ]] || \
        die "new bundle file conflicts with an untracked directory: $candidate_path"
    else
      [[ -n "${old_file_set[$relative_path]+present}" ]] || \
        die "new bundle file conflicts with an untracked path: $candidate_path"
    fi
  fi
done
for relative_path in "${new_dirs[@]}"; do
  candidate_path="$PREFIX/$relative_path"
  if [[ -e "$candidate_path" || -L "$candidate_path" ]]; then
    if [[ -d "$candidate_path" && ! -L "$candidate_path" ]]; then
      [[ -n "${old_dir_set[$relative_path]+present}" ]] || \
        die "new bundle directory conflicts with an untracked path: $candidate_path"
    else
      [[ -n "${old_file_set[$relative_path]+present}" ]] || \
        die "new bundle directory conflicts with an untracked path: $candidate_path"
    fi
  fi
done

# Avoid serving a mixture of old and new static assets during a portable upgrade.
# A system-scope payload may be used by several user managers, which root cannot stop
# safely on their behalf; administrators must stop those sessions before replacement.
if [[ "$managed_install" -eq 1 ]]; then
  if [[ "$SCOPE" == "user" && -x "$PREFIX/bin/lemma" ]]; then
    "$PREFIX/bin/lemma" stop >/dev/null || \
      die "could not stop the existing Lemma service before upgrade"
  elif [[ "$SCOPE" == "system" ]]; then
    warn "upgrading a system payload; ensure every user's Lemma service is stopped"
  fi
fi

# Remove only stale files named by the previous receipt. This supports upgrades
# without ever recursively deleting the application root.
if [[ "$managed_install" -eq 1 ]]; then
  for relative_path in "${old_files[@]}"; do
    if [[ -z "${new_file_set[$relative_path]+present}" ]]; then
      stale_path="$PREFIX/$relative_path"
      [[ ! -d "$stale_path" || -L "$stale_path" ]] || \
        die "old installed file became a directory: $stale_path"
      rm -f -- "$stale_path"
    fi
  done
  for relative_path in "${old_dirs[@]}"; do
    if [[ ! -d "$BUNDLE/$relative_path" ]]; then
      if [[ -f "$BUNDLE/$relative_path" && -d "$PREFIX/$relative_path" ]]; then
        rmdir -- "$PREFIX/$relative_path" 2>/dev/null || \
          die "cannot replace a managed directory containing untracked data: $PREFIX/$relative_path"
      else
        rmdir -- "$PREFIX/$relative_path" 2>/dev/null || true
      fi
    fi
  done
fi

receipt_integrations=("${desired_integrations[@]}")
for integration_path in "${old_integrations[@]}"; do
  already_recorded=0
  for desired_path in "${receipt_integrations[@]}"; do
    if [[ "$integration_path" == "$desired_path" ]]; then
      already_recorded=1
      break
    fi
  done
  [[ "$already_recorded" -eq 1 ]] || receipt_integrations+=("$integration_path")
done

# Build the complete receipt off to the side, then exchange directory names. If a
# later payload write fails (for example, a full disk), the canonical receipt still
# describes every path the interrupted operation may have created.
install -d -m 755 -- "$PREFIX" "$NEXT_MARKER"
printf '1\n' > "$NEXT_MARKER/format"
printf '%s\n' "$SCOPE" > "$NEXT_MARKER/scope"
printf '%s\n' "$PREFIX" > "$NEXT_MARKER/prefix"
printf '%s\n' "$VERSION" > "$NEXT_MARKER/version"
printf '%s\n' "${new_files[@]}" > "$NEXT_MARKER/installed-files"
printf '%s\n' "${new_dirs[@]}" > "$NEXT_MARKER/installed-directories"
printf '%s\n' "${receipt_integrations[@]}" > "$NEXT_MARKER/integration-paths"
printf '%s\n' "$CONFIG_PATH" > "$NEXT_MARKER/config-path"
printf '%s\n' "$DATA_PATH" > "$NEXT_MARKER/data-path"
printf '%s\n' "$STATE_PATH" > "$NEXT_MARKER/state-path"
printf '%s\n' "$WORKSPACES_PATH" > "$NEXT_MARKER/workspaces-path"
for receipt_file in "${receipt_files[@]}"; do
  chmod 644 -- "$NEXT_MARKER/$receipt_file"
done
if [[ -e "$MARKER" ]]; then
  mv -- "$MARKER" "$PREVIOUS_MARKER"
fi
if ! mv -- "$NEXT_MARKER" "$MARKER"; then
  if [[ ! -e "$MARKER" && -d "$PREVIOUS_MARKER" ]]; then
    mv -- "$PREVIOUS_MARKER" "$MARKER"
  fi
  die "could not activate the new installation receipt"
fi

cp -a --no-preserve=ownership -- "$BUNDLE/." "$PREFIX/"
if [[ "$SCOPE" == "system" ]]; then
  # This is a non-secret template read by each user's lemma-server process. The
  # private copy created in ~/.config/lemma/.env remains mode 0600.
  chmod 644 -- "$PREFIX/share/lemma/env.default"
else
  chmod 600 -- "$PREFIX/share/lemma/env.default"
fi

desktop_render=""
unit_render=""
integration_receipt_temp=""
cleanup_render_files() {
  [[ -z "$desktop_render" ]] || rm -f -- "$desktop_render"
  [[ -z "$unit_render" ]] || rm -f -- "$unit_render"
  [[ -z "$integration_receipt_temp" ]] || rm -f -- "$integration_receipt_temp"
}
trap cleanup_render_files EXIT
desktop_render="$(mktemp /tmp/lemma-install.desktop.XXXXXXXX)"
unit_render="$(mktemp /tmp/lemma-install.service.XXXXXXXX)"

sed "s|@LAUNCHER@|$PREFIX/bin/lemma|g" \
  "$BUNDLE/share/applications/io.lemma.Lemma.desktop.in" > "$desktop_render"
sed "s|@INSTALL_ROOT@|$PREFIX|g" \
  "$BUNDLE/share/systemd/user/lemma.service.in" > "$unit_render"
if grep -Fq '@LAUNCHER@' "$desktop_render" || \
   grep -Fq '@INSTALL_ROOT@' "$unit_render"; then
  die "could not render desktop or service template"
fi

replace_regular_file() {
  local source_file="$1"
  local target_file="$2"
  install -d -m 755 -- "$(dirname "$target_file")"
  [[ ! -d "$target_file" || -L "$target_file" ]] || \
    die "refusing to replace directory: $target_file"
  rm -f -- "$target_file"
  install -m 644 -- "$source_file" "$target_file"
}

replace_command_link() {
  local command_name="$1"
  local source_file="$PREFIX/bin/$command_name"
  local target_file="$BIN_DIR/$command_name"
  install -d -m 755 -- "$BIN_DIR"
  [[ ! -d "$target_file" || -L "$target_file" ]] || \
    die "refusing to replace directory: $target_file"
  rm -f -- "$target_file"
  ln -s -- "$source_file" "$target_file"
}

replace_command_link lemma
replace_command_link lemma-server
replace_command_link lemma-doctor
replace_regular_file "$desktop_render" "$DESKTOP_FILE"
replace_regular_file \
  "$BUNDLE/share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg" "$ICON_FILE"
replace_regular_file \
  "$BUNDLE/share/metainfo/io.lemma.Lemma.metainfo.xml" "$METAINFO_FILE"
replace_regular_file "$unit_render" "$UNIT_FILE"

# Remove integration files left at old XDG locations after a managed upgrade.
for integration_path in "${old_integrations[@]}"; do
  still_used=0
  for desired_path in "${desired_integrations[@]}"; do
    if [[ "$integration_path" == "$desired_path" ]]; then
      still_used=1
      break
    fi
  done
  [[ "$still_used" -eq 0 ]] || continue

  case "${integration_path##*/}" in
    lemma|lemma-server|lemma-doctor)
      if [[ -L "$integration_path" && \
            "$(readlink -- "$integration_path")" == "$PREFIX/bin/${integration_path##*/}" ]]; then
        rm -f -- "$integration_path"
      elif [[ -e "$integration_path" || -L "$integration_path" ]]; then
        warn "preserving changed command link at old location: $integration_path"
      fi
      ;;
    *)
      [[ -d "$integration_path" && ! -L "$integration_path" ]] || \
        rm -f -- "$integration_path"
      ;;
  esac
done

integration_receipt_temp="$(mktemp "$MARKER/.integration-paths.XXXXXXXX")"
printf '%s\n' "${desired_integrations[@]}" > "$integration_receipt_temp"
chmod 644 -- "$integration_receipt_temp"
mv -- "$integration_receipt_temp" "$MARKER/integration-paths"
integration_receipt_temp=""

cleanup_render_files
trap - EXIT
if [[ -e "$PREVIOUS_MARKER" || -L "$PREVIOUS_MARKER" ]]; then
  cleanup_receipt_directory "$PREVIOUS_MARKER"
fi

if [[ "$SCOPE" == "user" ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

printf 'Installed Lemma %s (%s) in %s\n' "$VERSION" "$SCOPE" "$PREFIX"
printf 'Command: %s/lemma\n' "$BIN_DIR"
printf 'Run "%s/lemma doctor" to check runtime dependencies.\n' "$BIN_DIR"
case ":${PATH:-}:" in
  *:"$BIN_DIR":*) ;;
  *) warn "$BIN_DIR is not currently on PATH" ;;
esac

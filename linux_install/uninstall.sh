#!/usr/bin/env bash
# Remove only paths recorded by install.sh. User data is preserved by default.
set -euo pipefail
umask 022

PROGRAM_NAME="${0##*/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PREFIX=""
SCOPE="user"
SCOPE_SET=0
purge_targets=()

usage() {
  cat <<'EOF'
Usage: uninstall.sh [OPTIONS]

Remove a receipt-managed Lemma Linux installation. By default this removes only
the immutable application and its command/desktop/service integration. It keeps:

  ${XDG_CONFIG_HOME:-~/.config}/lemma
  ${XDG_DATA_HOME:-~/.local/share}/lemma
  ${XDG_STATE_HOME:-~/.local/state}/lemma
  ~/ai-company-workspaces

Options:
  --prefix DIRECTORY  Application root used at install time
                      (default: ~/.local/opt/lemma for --user,
                      /opt/lemma for --system)
  --user              Uninstall for the current user (default)
  --system            Uninstall a system-wide installation; requires root
  --purge TARGET      Also delete exactly one mutable user-data tree. Repeat for
                      more than one. TARGET is config, data, state, or workspaces.
                      This option is rejected for --system installations.
  -h, --help          Show this help

There is deliberately no broad "purge all" operation. Workspace deletion always
requires the explicit option: --purge workspaces.
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

add_purge_target() {
  case "$1" in
    config|data|state|workspaces) purge_targets+=("$1") ;;
    *) die "unknown purge target: $1 (expected config, data, state, or workspaces)" ;;
  esac
}

while (($#)); do
  case "$1" in
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
    --purge)
      need_value "$@"
      add_purge_target "$2"
      shift 2
      ;;
    --purge=*)
      purge_value="${1#*=}"
      [[ -n "$purge_value" ]] || die "missing value for --purge"
      add_purge_target "$purge_value"
      shift
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

[[ "$(uname -s)" == "Linux" ]] || die "this uninstaller runs only on Linux"
((BASH_VERSINFO[0] >= 4)) || die "Bash 4 or newer is required"
for command_name in find mv readlink realpath rm rmdir stat; do
  command -v "$command_name" >/dev/null 2>&1 || \
    die "required command is unavailable: $command_name"
done
[[ -n "${HOME:-}" && "$HOME" == /* ]] || die "HOME must be an absolute path"

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
    die "install root contains unsafe characters: $candidate"
}

if [[ -z "$PREFIX" ]]; then
  if [[ ( -d "$SCRIPT_DIR/.lemma-install" && ! -L "$SCRIPT_DIR/.lemma-install" ) ||
        ( -d "$SCRIPT_DIR/.lemma-install.previous" &&
          ! -L "$SCRIPT_DIR/.lemma-install.previous" ) ]]; then
    # An installed top-level copy knows its own custom prefix. Repository copies
    # have no receipt beside them and continue to use the scope-specific default.
    PREFIX="$SCRIPT_DIR"
  elif [[ "$SCOPE" == "user" ]]; then
    PREFIX="$HOME/.local/opt/lemma"
  else
    PREFIX="/opt/lemma"
  fi
fi
PREFIX="$(normalize_path "$PREFIX" "install root")"
validate_install_root "$PREFIX"

[[ ! -L "$PREFIX" ]] || die "install root must not be a symbolic link: $PREFIX"
if [[ ! -e "$PREFIX" ]]; then
  printf 'Lemma is not installed at %s\n' "$PREFIX"
  exit 0
fi
[[ -d "$PREFIX" ]] || die "install root is not a directory: $PREFIX"
[[ "$(stat -c '%u' -- "$PREFIX")" == "$EUID" ]] || \
  die "install root is not owned by the uninstalling user: $PREFIX"

MARKER="$PREFIX/.lemma-install"
NEXT_MARKER="$PREFIX/.lemma-install.next"
PREVIOUS_MARKER="$PREFIX/.lemma-install.previous"
marker_files=(
  format
  scope
  prefix
  version
  installed-files
  installed-directories
  integration-paths
  config-path
  data-path
  state-path
  workspaces-path
)
if [[ ! -e "$MARKER" && \
      ( -e "$PREVIOUS_MARKER" || -L "$PREVIOUS_MARKER" ) ]]; then
  [[ -d "$PREVIOUS_MARKER" && ! -L "$PREVIOUS_MARKER" ]] || \
    die "previous installation receipt is unsafe"
  [[ "$(stat -c '%u' -- "$PREVIOUS_MARKER")" == "$EUID" ]] || \
    die "previous installation receipt is not owned by the uninstalling user"
  mv -- "$PREVIOUS_MARKER" "$MARKER"
fi
[[ -d "$MARKER" && ! -L "$MARKER" ]] || \
  die "no safe Lemma installation receipt exists at $MARKER"

read_owned_file() {
  local file_path="$1"
  [[ -f "$file_path" && ! -L "$file_path" ]] || \
    die "installation metadata is missing or unsafe: $file_path"
  [[ "$(stat -c '%u' -- "$file_path")" == "$EUID" ]] || \
    die "installation metadata is not owned by the uninstalling user: $file_path"
  REPLY=""
  IFS= read -r REPLY < "$file_path" || true
}

read_owned_file "$MARKER/format"
[[ "$REPLY" == "1" ]] || die "unsupported installation receipt format"
read_owned_file "$MARKER/prefix"
[[ "$REPLY" == "$PREFIX" ]] || \
  die "installation was moved from its recorded prefix: $REPLY"
read_owned_file "$MARKER/scope"
RECORDED_SCOPE="$REPLY"
[[ "$RECORDED_SCOPE" == "user" || "$RECORDED_SCOPE" == "system" ]] || \
  die "installation receipt has an invalid scope"
if [[ "$SCOPE_SET" -eq 1 && "$SCOPE" != "$RECORDED_SCOPE" ]]; then
  die "installation uses --$RECORDED_SCOPE, not --$SCOPE"
fi
SCOPE="$RECORDED_SCOPE"
if [[ "$SCOPE" == "system" && "$EUID" -ne 0 ]]; then
  die "uninstalling a system installation requires root"
fi
if [[ "$SCOPE" == "system" && ${#purge_targets[@]} -gt 0 ]]; then
  die "--purge is available only for a per-user installation"
fi

receipt_files=(
  installed-files
  installed-directories
  integration-paths
  config-path
  data-path
  state-path
  workspaces-path
)
for receipt_file in "${receipt_files[@]}"; do
  [[ -f "$MARKER/$receipt_file" && ! -L "$MARKER/$receipt_file" ]] || \
    die "installation receipt is incomplete: $receipt_file"
  [[ "$(stat -c '%u' -- "$MARKER/$receipt_file")" == "$EUID" ]] || \
    die "installation receipt is not owned by the uninstalling user"
done

validate_relative_path() {
  local relative_path="$1"
  [[ -n "$relative_path" && "$relative_path" != /* ]] || return 1
  [[ "$relative_path" != "." && "$relative_path" != ".." ]] || return 1
  [[ "$relative_path" != ../* && "$relative_path" != */../* && \
     "$relative_path" != */.. ]] || return 1
  [[ "$relative_path" != *$'\n'* && "$relative_path" != *$'\r'* ]] || return 1
  [[ "$relative_path" =~ ^[A-Za-z0-9._/+@=,:!~-]+$ ]] || return 1
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

mapfile -t installed_files < "$MARKER/installed-files"
mapfile -t installed_dirs < "$MARKER/installed-directories"
mapfile -t integration_paths < "$MARKER/integration-paths"
for relative_path in "${installed_files[@]}" "${installed_dirs[@]}"; do
  validate_relative_path "$relative_path" || \
    die "installation receipt contains an unsafe relative path"
done
for integration_path in "${integration_paths[@]}"; do
  safe_integration_path "$integration_path" || \
    die "installation receipt contains an unsafe integration path"
done

read_owned_file "$MARKER/config-path"
CONFIG_PATH="$REPLY"
read_owned_file "$MARKER/data-path"
DATA_PATH="$REPLY"
read_owned_file "$MARKER/state-path"
STATE_PATH="$REPLY"
read_owned_file "$MARKER/workspaces-path"
WORKSPACES_PATH="$REPLY"

validate_mutable_path() {
  local candidate="$1"
  local required_name="$2"
  [[ "$candidate" == /* && "$candidate" != *$'\n'* && \
     "$candidate" != *$'\r'* ]] || return 1
  [[ "${candidate##*/}" == "$required_name" ]] || return 1
  case "$candidate" in /|/home|/root|/tmp|/var|/usr|/opt) return 1 ;; esac
}

if [[ "$SCOPE" == "user" ]]; then
  validate_mutable_path "$CONFIG_PATH" lemma || die "unsafe recorded config path"
  validate_mutable_path "$DATA_PATH" lemma || die "unsafe recorded data path"
  validate_mutable_path "$STATE_PATH" lemma || die "unsafe recorded state path"
  validate_mutable_path "$WORKSPACES_PATH" ai-company-workspaces || \
    die "unsafe recorded workspace path"
  mutable_paths=("$CONFIG_PATH" "$DATA_PATH" "$STATE_PATH" "$WORKSPACES_PATH")
  if ((${#purge_targets[@]} > 0)); then
    for mutable_path in "${mutable_paths[@]}"; do
      paths_overlap "$PREFIX" "$mutable_path" && \
        die "recorded mutable path overlaps the install root: $mutable_path"
    done
    for ((first_index = 0; first_index < ${#mutable_paths[@]}; first_index++)); do
      for ((second_index = first_index + 1; \
            second_index < ${#mutable_paths[@]}; second_index++)); do
        if paths_overlap "${mutable_paths[$first_index]}" \
          "${mutable_paths[$second_index]}"; then
          die "recorded mutable user-data paths overlap; refusing purge"
        fi
      done
    done
  fi
fi

# A bundle produced by build.sh contains no symbolic links. Refusing an altered
# tree prevents a replaced parent directory from redirecting exact-file removal.
if [[ -n "$(find "$PREFIX" -type l -print -quit)" ]]; then
  die "install root contains a symbolic link; refusing unsafe removal"
fi

if [[ "$SCOPE" == "user" ]]; then
  if [[ -x "$PREFIX/bin/lemma" ]]; then
    if ! "$PREFIX/bin/lemma" stop >/dev/null 2>&1; then
      if ((${#purge_targets[@]} > 0)); then
        die "could not stop Lemma; refusing to purge live mutable data"
      fi
      warn "could not stop a running Lemma process; continuing with exact-file removal"
    fi
  elif command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-active --quiet lemma.service >/dev/null 2>&1 && \
       ! systemctl --user stop lemma.service >/dev/null 2>&1; then
      if ((${#purge_targets[@]} > 0)); then
        die "could not stop Lemma; refusing to purge live mutable data"
      fi
      warn "could not stop the active Lemma user service"
    fi
  fi
fi

for integration_path in "${integration_paths[@]}"; do
  case "${integration_path##*/}" in
    lemma|lemma-server|lemma-doctor)
      expected_target="$PREFIX/bin/${integration_path##*/}"
      if [[ -L "$integration_path" ]]; then
        if [[ "$(readlink -- "$integration_path")" == "$expected_target" ]]; then
          rm -f -- "$integration_path"
        else
          warn "preserving changed command link: $integration_path"
        fi
      elif [[ -e "$integration_path" ]]; then
        warn "preserving command path that is no longer Lemma's link: $integration_path"
      fi
      ;;
    *)
      if [[ -d "$integration_path" && ! -L "$integration_path" ]]; then
        warn "preserving integration path that became a directory: $integration_path"
      else
        rm -f -- "$integration_path"
      fi
      ;;
  esac
done

for relative_path in "${installed_files[@]}"; do
  installed_path="$PREFIX/$relative_path"
  if [[ -d "$installed_path" && ! -L "$installed_path" ]]; then
    warn "preserving installed-file path that became a directory: $installed_path"
  else
    rm -f -- "$installed_path"
  fi
done

for marker_file in "${marker_files[@]}"; do
  rm -f -- "$MARKER/$marker_file"
done
for marker_temp in "$MARKER"/.desktop.???????? "$MARKER"/.service.???????? \
  "$MARKER"/.integration-paths.????????; do
  if [[ -f "$marker_temp" && ! -L "$marker_temp" && \
        "$(stat -c '%u' -- "$marker_temp")" == "$EUID" ]]; then
    rm -f -- "$marker_temp"
  fi
done
rmdir -- "$MARKER" 2>/dev/null || true

cleanup_auxiliary_receipt() {
  local receipt_directory="$1"
  local marker_file
  local marker_temp
  [[ -d "$receipt_directory" && ! -L "$receipt_directory" ]] || \
    die "auxiliary installation receipt is unsafe: $receipt_directory"
  [[ "$(stat -c '%u' -- "$receipt_directory")" == "$EUID" ]] || \
    die "auxiliary installation receipt is not owned by the uninstalling user"
  for marker_file in "${marker_files[@]}"; do
    if [[ -e "$receipt_directory/$marker_file" || \
          -L "$receipt_directory/$marker_file" ]]; then
      [[ -f "$receipt_directory/$marker_file" && \
         ! -L "$receipt_directory/$marker_file" ]] || \
        die "auxiliary installation receipt contains an unsafe path"
      rm -f -- "$receipt_directory/$marker_file"
    fi
  done
  for marker_temp in "$receipt_directory"/.desktop.???????? \
    "$receipt_directory"/.service.???????? \
    "$receipt_directory"/.integration-paths.????????; do
    if [[ -e "$marker_temp" || -L "$marker_temp" ]]; then
      [[ -f "$marker_temp" && ! -L "$marker_temp" ]] || \
        die "auxiliary installation receipt contains an unsafe temporary path"
      rm -f -- "$marker_temp"
    fi
  done
  rmdir -- "$receipt_directory" 2>/dev/null || \
    die "auxiliary installation receipt contains an unexpected path"
}
for auxiliary_receipt in "$NEXT_MARKER" "$PREVIOUS_MARKER"; do
  if [[ -e "$auxiliary_receipt" || -L "$auxiliary_receipt" ]]; then
    cleanup_auxiliary_receipt "$auxiliary_receipt"
  fi
done

# install.sh records directories in find -depth order, so children are attempted
# before parents. rmdir removes only empty directories and preserves untracked data.
for relative_path in "${installed_dirs[@]}"; do
  rmdir -- "$PREFIX/$relative_path" 2>/dev/null || true
done
rmdir -- "$PREFIX" 2>/dev/null || true

if [[ "$SCOPE" == "user" ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

purge_tree() {
  local label="$1"
  local target_path="$2"
  local required_name="$3"
  validate_mutable_path "$target_path" "$required_name" || \
    die "refusing unsafe $label purge path: $target_path"
  ! paths_overlap "$target_path" "$PREFIX" || \
    die "purge path collides with install root"
  if [[ -L "$target_path" ]]; then
    die "refusing to purge a symbolic link: $target_path"
  fi
  if [[ -e "$target_path" ]]; then
    [[ -d "$target_path" ]] || die "$label purge target is not a directory: $target_path"
    [[ "$(stat -c '%u' -- "$target_path")" == "$EUID" ]] || \
      die "$label purge target is not owned by the current user: $target_path"
    # find does not follow nested symbolic links; -xdev avoids crossing a mount.
    find "$target_path" -xdev -depth -delete
    printf 'Purged %s: %s\n' "$label" "$target_path"
  fi
}

declare -A purged=()
for purge_target in "${purge_targets[@]}"; do
  [[ -z "${purged[$purge_target]+present}" ]] || continue
  purged["$purge_target"]=1
  case "$purge_target" in
    config) purge_tree config "$CONFIG_PATH" lemma ;;
    data) purge_tree data "$DATA_PATH" lemma ;;
    state) purge_tree state "$STATE_PATH" lemma ;;
    workspaces) purge_tree workspaces "$WORKSPACES_PATH" ai-company-workspaces ;;
  esac
done

printf 'Removed Lemma application files from %s\n' "$PREFIX"
if [[ -e "$PREFIX" ]]; then
  warn "untracked or changed files remain under $PREFIX; they were preserved"
fi
if [[ "$SCOPE" == "user" ]]; then
  [[ -n "${purged[config]+present}" ]] || printf 'Preserved config: %s\n' "$CONFIG_PATH"
  [[ -n "${purged[data]+present}" ]] || printf 'Preserved data: %s\n' "$DATA_PATH"
  [[ -n "${purged[state]+present}" ]] || printf 'Preserved state: %s\n' "$STATE_PATH"
  [[ -n "${purged[workspaces]+present}" ]] || \
    printf 'Preserved workspaces: %s\n' "$WORKSPACES_PATH"
else
  printf 'Per-user Lemma configuration, data, state, and workspaces were not touched.\n'
fi

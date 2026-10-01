#!/usr/bin/env bash
# Authenticate a Lemma bundle manifest or distributable archive with minisign.
set -euo pipefail
umask 022

PROGRAM_NAME="${0##*/}"
BUNDLE=""
ARTIFACT=""
PUBLIC_KEY=""

usage() {
  cat <<'EOF'
Usage:
  verify-release.sh --public-key FILE --bundle DIRECTORY
  verify-release.sh --public-key FILE --artifact ARCHIVE_OR_PACKAGE

Authenticate a signed Lemma release using a trusted minisign public-key file.
Bundle mode verifies manifest.sha256.minisig first, then checks complete manifest
coverage, every payload hash, and the CycloneDX SBOM. Artifact mode verifies the
detached FILE.minisig signature and the exact FILE.sha256 checksum.

Options:
  --public-key FILE  Trusted minisign public-key file (required)
  --bundle DIRECTORY Unpacked Lemma bundle to authenticate
  --artifact FILE    Portable .tar.gz or Debian .deb to authenticate
  -h, --help         Show this help
EOF
}

die() {
  printf '%s: ERROR: %s\n' "$PROGRAM_NAME" "$*" >&2
  exit 1
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "missing value for $1"
}

while (($#)); do
  case "$1" in
    --public-key)
      need_value "$@"
      PUBLIC_KEY="$2"
      shift 2
      ;;
    --bundle)
      need_value "$@"
      BUNDLE="$2"
      shift 2
      ;;
    --artifact)
      need_value "$@"
      ARTIFACT="$2"
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

[[ -n "$PUBLIC_KEY" ]] || die "--public-key FILE is required"
if [[ -n "$BUNDLE" && -n "$ARTIFACT" ]] || [[ -z "$BUNDLE" && -z "$ARTIFACT" ]]; then
  die "choose exactly one of --bundle or --artifact"
fi
for command_name in basename dirname find minisign python3 realpath sha256sum sort; do
  command -v "$command_name" >/dev/null 2>&1 || \
    die "required verification command is unavailable: $command_name"
done
[[ -f "$PUBLIC_KEY" && ! -L "$PUBLIC_KEY" ]] || \
  die "trusted public key must be a regular, non-symbolic-link file: $PUBLIC_KEY"
PUBLIC_KEY="$(realpath -e -- "$PUBLIC_KEY")"

if [[ -n "$ARTIFACT" ]]; then
  [[ -f "$ARTIFACT" && ! -L "$ARTIFACT" ]] || \
    die "artifact must be a regular, non-symbolic-link file: $ARTIFACT"
  ARTIFACT="$(realpath -e -- "$ARTIFACT")"
  signature="$ARTIFACT.minisig"
  checksum="$ARTIFACT.sha256"
  [[ -f "$signature" && ! -L "$signature" ]] || \
    die "detached artifact signature is missing or unsafe: $signature"
  [[ -f "$checksum" && ! -L "$checksum" ]] || \
    die "artifact checksum is missing or unsafe: $checksum"

  minisign -V -q -p "$PUBLIC_KEY" -m "$ARTIFACT" -x "$signature" || \
    die "artifact signature verification failed"
  artifact_name="$(basename "$ARTIFACT")"
  IFS= read -r checksum_line < "$checksum" || true
  checksum_hash="${checksum_line:0:64}"
  checksum_separator="${checksum_line:64:2}"
  checksum_name="${checksum_line:66}"
  [[ "$checksum_hash" =~ ^[0-9a-f]{64}$ && \
     "$checksum_separator" == "  " && "$checksum_name" == "$artifact_name" ]] || \
    die "checksum file does not name exactly $artifact_name"
  if ! (cd "$(dirname "$ARTIFACT")" && \
    sha256sum --check --strict --quiet "$(basename "$checksum")"); then
    die "artifact checksum verification failed"
  fi
  printf 'Authenticated release artifact: %s\n' "$ARTIFACT"
  exit 0
fi

[[ -d "$BUNDLE" && ! -L "$BUNDLE" ]] || \
  die "bundle must be a real directory: $BUNDLE"
BUNDLE="$(realpath -e -- "$BUNDLE")"
[[ "$BUNDLE" != "/" ]] || die "refusing to verify the filesystem root"
manifest="$BUNDLE/manifest.sha256"
signature="$BUNDLE/manifest.sha256.minisig"
sbom="$BUNDLE/share/doc/lemma-linux/SBOM.cdx.json"
sbom_tool="$BUNDLE/share/lemma/app/linux_install/sbom.py"
for required_path in "$manifest" "$signature" "$sbom" "$sbom_tool" "$BUNDLE/VERSION"; do
  [[ -f "$required_path" && ! -L "$required_path" ]] || \
    die "signed bundle is missing a required regular file: ${required_path#"$BUNDLE/"}"
done
unexpected_path="$(find "$BUNDLE" \( -type l -o \( ! -type d -a ! -type f \) \) \
  -print -quit)"
[[ -z "$unexpected_path" ]] || \
  die "bundle contains an unsupported link or special file: $unexpected_path"

# Authenticate the manifest before treating any path named by it as trusted input.
minisign -V -q -p "$PUBLIC_KEY" -m "$manifest" -x "$signature" || \
  die "bundle manifest signature verification failed"

validate_relative_path() {
  local relative_path="$1"
  [[ -n "$relative_path" && "$relative_path" != /* ]] || return 1
  [[ "$relative_path" != "." && "$relative_path" != ".." ]] || return 1
  [[ "$relative_path" != ../* && "$relative_path" != */../* && \
     "$relative_path" != */.. ]] || return 1
  [[ "$relative_path" != *$'\n'* && "$relative_path" != *$'\r'* ]] || return 1
  [[ "$relative_path" =~ ^[A-Za-z0-9._/+@=,:!~-]+$ ]] || return 1
}

declare -A manifest_paths=()
manifest_count=0
while IFS= read -r checksum_line || [[ -n "$checksum_line" ]]; do
  [[ "$checksum_line" =~ ^[0-9a-f]{64}\ \ \./ ]] || \
    die "manifest.sha256 has an unsupported or unsafe entry"
  relative_path="${checksum_line:68}"
  validate_relative_path "$relative_path" || \
    die "manifest.sha256 contains an unsafe path: $relative_path"
  [[ "$relative_path" != "manifest.sha256" && \
     "$relative_path" != "manifest.sha256.minisig" ]] || \
    die "the detached manifest and its signature must not list themselves"
  [[ -z "${manifest_paths[$relative_path]+present}" ]] || \
    die "manifest.sha256 contains a duplicate path: $relative_path"
  [[ -f "$BUNDLE/$relative_path" && ! -L "$BUNDLE/$relative_path" ]] || \
    die "manifest.sha256 names a missing or unsafe file: $relative_path"
  manifest_paths["$relative_path"]=1
  manifest_count=$((manifest_count + 1))
done < "$manifest"
((manifest_count > 0)) || die "manifest.sha256 is empty"

actual_file_count=0
while IFS= read -r -d '' relative_path; do
  relative_path="${relative_path#./}"
  validate_relative_path "$relative_path" || die "bundle contains an unsafe file name"
  actual_file_count=$((actual_file_count + 1))
  if [[ "$relative_path" != "manifest.sha256" && \
        "$relative_path" != "manifest.sha256.minisig" && \
        -z "${manifest_paths[$relative_path]+present}" ]]; then
    die "bundle file is not covered by manifest.sha256: $relative_path"
  fi
done < <(cd "$BUNDLE" && find . -mindepth 1 -type f -print0 | LC_ALL=C sort -z)
[[ "$actual_file_count" -eq $((manifest_count + 2)) ]] || \
  die "manifest.sha256 does not describe the complete signed bundle"
if ! (cd "$BUNDLE" && sha256sum --check --strict --quiet manifest.sha256); then
  die "bundle checksum verification failed"
fi

mapfile -t version_lines < "$BUNDLE/VERSION"
[[ "${#version_lines[@]}" -eq 1 ]] || die "VERSION must contain exactly one line"
python3 -I -B "$sbom_tool" validate "$sbom" \
  --application-version "${version_lines[0]}" || die "bundle SBOM validation failed"
printf 'Authenticated release bundle: %s\n' "$BUNDLE"

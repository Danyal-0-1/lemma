#!/usr/bin/env bash
# Build an offline, architecture-specific Linux release bundle.
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
OUTPUT_DIR="$SCRIPT_DIR/dist"
KEEP_WORK=0
SIGNING_KEY=""

usage() {
  cat <<'EOF'
Usage: ./linux_install/build.sh [--output DIRECTORY] [--keep-work]
                                [--minisign-secret-key FILE]

Builds Lemma without network access. npm and uv must already have every locked
dependency in their local caches. Run this on the oldest Linux/Python combination
you intend to support; native Python wheels are bundled for that architecture and
exact Python minor version.

When --minisign-secret-key is supplied, minisign creates detached signatures for
the bundle manifest and portable archive. Signing is optional and never contacts
the network; distribute the corresponding public key through a separate trusted
channel.
EOF
}

while (($#)); do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || { printf 'Missing value for --output\n' >&2; exit 2; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --keep-work)
      KEEP_WORK=1
      shift
      ;;
    --minisign-secret-key)
      [[ $# -ge 2 && -n "$2" ]] || {
        printf 'Missing value for --minisign-secret-key\n' >&2
        exit 2
      }
      SIGNING_KEY="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$SIGNING_KEY" ]]; then
  [[ -f "$SIGNING_KEY" && ! -L "$SIGNING_KEY" ]] || {
    printf 'Minisign secret key must be a regular, non-symbolic-link file: %s\n' \
      "$SIGNING_KEY" >&2
    exit 1
  }
  command -v minisign >/dev/null 2>&1 || {
    printf 'minisign is required only when --minisign-secret-key is used.\n' >&2
    exit 1
  }
fi

[[ "$(uname -s)" == "Linux" ]] || {
  printf 'build.sh creates native Linux artifacts and must run on Linux.\n' >&2
  exit 1
}

for command_name in basename cat chmod cp cut date dirname env find git grep gzip \
  install mkdir mktemp mv node npm python3 rm sha256sum sort tar uname uv xargs; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'Required build command is unavailable: %s\n' "$command_name" >&2
    exit 1
  }
done

node_major="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$node_major" =~ ^[0-9]+$ && "$node_major" -ge 20 ]] || {
  printf 'Node 20 or newer is required.\n' >&2
  exit 1
}
python_abi="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python_ok="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 12)))')"
[[ "$python_ok" == "1" ]] || {
  printf 'Python 3.12 or newer is required.\n' >&2
  exit 1
}

version="$(node -e 'console.log(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).version)' "$REPO_ROOT/frontend/package.json")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)*$ ]] || {
  printf 'Refusing unexpected application version: %s\n' "$version" >&2
  exit 1
}
version_report="$(python3 - "$REPO_ROOT/backend/pyproject.toml" \
  "$REPO_ROOT/backend/app/main.py" <<'PY'
import ast
import sys
import tomllib

with open(sys.argv[1], "rb") as project_file:
    backend_version = tomllib.load(project_file)["project"]["version"]
with open(sys.argv[2], encoding="utf-8") as source_file:
    syntax_tree = ast.parse(source_file.read())
server_version = next(
    statement.value.value
    for statement in syntax_tree.body
    if isinstance(statement, ast.Assign)
    and any(
        isinstance(target, ast.Name) and target.id == "SERVER_VERSION"
        for target in statement.targets
    )
    and isinstance(statement.value, ast.Constant)
)
print(f"{backend_version}\t{server_version}")
PY
)"
IFS=$'\t' read -r backend_version server_version <<< "$version_report"
if [[ "$backend_version" != "$version" || "$server_version" != "$version" ]]; then
  printf 'Version mismatch: frontend=%s backend=%s server=%s\n' \
    "$version" "$backend_version" "$server_version" >&2
  exit 1
fi

case "$(uname -m)" in
  x86_64|amd64) release_arch="x86_64" ;;
  aarch64|arm64) release_arch="aarch64" ;;
  *)
    printf 'Unsupported Linux architecture: %s\n' "$(uname -m)" >&2
    exit 1
    ;;
esac

epoch="${SOURCE_DATE_EPOCH:-$(git -C "$REPO_ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}"
[[ "$epoch" =~ ^[0-9]+$ ]] || {
  printf 'SOURCE_DATE_EPOCH must be a non-negative integer.\n' >&2
  exit 1
}

install -d -m 755 -- "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"

bundle_name="lemma-$version-linux-$release_arch"
final_dir="$OUTPUT_DIR/$bundle_name"
archive="$OUTPUT_DIR/$bundle_name.tar.gz"
archive_checksum="$archive.sha256"
archive_signature="$archive.minisig"
output_paths=("$final_dir" "$archive" "$archive_checksum" "$archive_signature")
for output_path in "${output_paths[@]}"; do
  [[ ! -e "$output_path" ]] || {
    printf 'Output already exists; remove it explicitly before rebuilding: %s\n' \
      "$output_path" >&2
    exit 1
  }
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/lemma-linux-build.XXXXXXXX")"
cleanup() {
  if [[ "$KEEP_WORK" -eq 1 ]]; then
    printf 'Build work directory retained at %s\n' "$work_dir"
  else
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT

bundle="$work_dir/$bundle_name"
frontend_build="$work_dir/frontend"
requirements="$work_dir/requirements.txt"

printf '[1/6] Building the production frontend from the npm offline cache...\n'
mkdir -m 755 -- "$frontend_build"
for file_name in package.json package-lock.json tsconfig.json vite.config.ts \
  postcss.config.js tailwind.config.js index.html; do
  cp -- "$REPO_ROOT/frontend/$file_name" "$frontend_build/$file_name"
done
cp -a -- "$REPO_ROOT/frontend/src" "$REPO_ROOT/frontend/public" \
  "$REPO_ROOT/frontend/scripts" "$frontend_build/"
(
  cd "$frontend_build"
  npm ci --offline --ignore-scripts --no-audit --no-fund
  # Vite exposes VITE_* variables to browser code. Never let a developer's shell
  # silently bake a non-loopback API origin into a distributable release.
  env -u VITE_BACKEND_ORIGIN npm run build
)

printf '[2/6] Exporting locked Python runtime dependencies...\n'
uv export --directory "$REPO_ROOT/backend" --frozen --no-dev --no-emit-project \
  --format requirements.txt --output-file "$requirements"

install -d -m 755 -- "$bundle/bin" "$bundle/libexec" \
  "$bundle/share/lemma/app/backend" "$bundle/share/lemma/app/frontend" \
  "$bundle/share/lemma/app/scripts" "$bundle/share/lemma/python" \
  "$bundle/share/lemma/web" "$bundle/share/applications" \
  "$bundle/share/icons/hicolor/scalable/apps" "$bundle/share/metainfo" \
  "$bundle/share/systemd/user" "$bundle/share/doc/lemma-linux"

printf '[3/6] Installing Python dependencies from the uv offline cache...\n'
uv pip install --target "$bundle/share/lemma/python" --python python3 \
  --requirements "$requirements" --offline --no-python-downloads \
  --require-hashes --link-mode copy
# Installed payloads can be read-only, and archive timestamp normalization would make
# build-time bytecode stale anyway. The service disables cache writes at runtime.
find "$bundle/share/lemma/python" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$bundle/share/lemma/python" -depth -type d -name '__pycache__' -empty -delete

printf '[4/6] Assembling the source worktree and runtime...\n'
for file_name in README.md SECURITY.md ARCHITECTURE.md LEARNING_PATH.md PROMPT.md \
  CLAUDE.md Makefile LICENSE .gitignore; do
  cp -- "$REPO_ROOT/$file_name" "$bundle/share/lemma/app/$file_name"
done
cp -a -- "$REPO_ROOT/backend/app" "$REPO_ROOT/backend/migrations" \
  "$bundle/share/lemma/app/backend/"
# The source worktree is intentionally included for learning and local inspection,
# but interpreter caches are machine-generated and can leak host-specific paths.
find "$bundle/share/lemma/app/backend" -type f \( -name '*.pyc' -o -name '*.pyo' \) \
  -delete
find "$bundle/share/lemma/app/backend" -depth -type d -name '__pycache__' \
  -empty -delete
for file_name in alembic.ini config.toml pyproject.toml uv.lock .env.example; do
  cp -- "$REPO_ROOT/backend/$file_name" "$bundle/share/lemma/app/backend/$file_name"
done
cp -a -- "$REPO_ROOT/frontend/src" "$REPO_ROOT/frontend/public" \
  "$REPO_ROOT/frontend/scripts" "$bundle/share/lemma/app/frontend/"
for file_name in package.json package-lock.json tsconfig.json vite.config.ts \
  postcss.config.js tailwind.config.js index.html; do
  cp -- "$REPO_ROOT/frontend/$file_name" "$bundle/share/lemma/app/frontend/$file_name"
done
cp -- "$REPO_ROOT/scripts/dev.sh" "$bundle/share/lemma/app/scripts/dev.sh"

# Keep the release pipeline itself visible in the installed source explorer, while
# excluding generated archives to avoid recursively packaging a release.
install -d -m 755 -- "$bundle/share/lemma/app/linux_install"
cp -- "$SCRIPT_DIR/README.md" "$SCRIPT_DIR/build.sh" "$SCRIPT_DIR/build-deb.sh" \
  "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/uninstall.sh" \
  "$SCRIPT_DIR/verify-release.sh" "$SCRIPT_DIR/sbom.py" \
  "$bundle/share/lemma/app/linux_install/"
cp -a -- "$SCRIPT_DIR/assets" "$SCRIPT_DIR/runtime" "$SCRIPT_DIR/packaging" \
  "$bundle/share/lemma/app/linux_install/"
find "$bundle/share/lemma/app/linux_install/runtime" -type f \
  \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$bundle/share/lemma/app/linux_install/runtime" -depth -type d \
  -name '__pycache__' -empty -delete

cp -a -- "$frontend_build/dist/." "$bundle/share/lemma/web/"
install -m 755 -- "$SCRIPT_DIR/runtime/lemma" "$bundle/bin/lemma"
install -m 755 -- "$SCRIPT_DIR/runtime/lemma-server" "$bundle/bin/lemma-server"
install -m 755 -- "$SCRIPT_DIR/runtime/lemma-doctor" "$bundle/bin/lemma-doctor"
install -m 644 -- "$SCRIPT_DIR/runtime/frontend_server.py" \
  "$bundle/libexec/frontend_server.py"
install -m 644 -- "$SCRIPT_DIR/runtime/backend_runner.py" \
  "$bundle/libexec/backend_runner.py"
install -m 600 -- "$SCRIPT_DIR/assets/env.default" "$bundle/share/lemma/env.default"
install -m 644 -- "$SCRIPT_DIR/assets/io.lemma.Lemma.desktop.in" \
  "$bundle/share/applications/io.lemma.Lemma.desktop.in"
install -m 644 -- "$SCRIPT_DIR/assets/io.lemma.Lemma.svg" \
  "$bundle/share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg"
install -m 644 -- "$SCRIPT_DIR/assets/io.lemma.Lemma.metainfo.xml" \
  "$bundle/share/metainfo/io.lemma.Lemma.metainfo.xml"
install -m 644 -- "$SCRIPT_DIR/assets/lemma.service.in" \
  "$bundle/share/systemd/user/lemma.service.in"
install -m 644 -- "$SCRIPT_DIR/README.md" "$bundle/share/doc/lemma-linux/README.md"
install -m 644 -- "$REPO_ROOT/LICENSE" "$bundle/share/doc/lemma-linux/LICENSE"
install -m 755 -- "$SCRIPT_DIR/install.sh" "$bundle/install.sh"
install -m 755 -- "$SCRIPT_DIR/uninstall.sh" "$bundle/uninstall.sh"
install -m 755 -- "$SCRIPT_DIR/verify-release.sh" "$bundle/verify-release.sh"

# The browser bundle and private Python library contain third-party code. Python
# wheels retain their dist-info license directories; npm packages do not ship beside
# Vite's compiled assets, so preserve their license files explicitly and inventory
# both ecosystems in one human-readable notice.
javascript_licenses="$bundle/share/doc/lemma-linux/third-party/javascript"
install -d -m 755 -- "$javascript_licenses"
(
  cd "$frontend_build"
  while IFS= read -r -d '' license_file; do
    destination="$javascript_licenses/$license_file"
    install -d -m 755 -- "$(dirname "$destination")"
    install -m 644 -- "$license_file" "$destination"
  done < <(
    find node_modules -type f \( -iname 'license*' -o -iname 'licence*' \
      -o -iname 'notice*' -o -iname 'copying*' \) -print0
  )
)

notices="$bundle/share/doc/lemma-linux/THIRD_PARTY_NOTICES.md"
cat > "$notices" <<'EOF'
# Third-party notices

Lemma includes open-source JavaScript and Python dependencies. This inventory is
informational; each dependency remains governed by its own license.

JavaScript license texts are preserved below `third-party/javascript/node_modules/`.
Python wheel license texts remain beside their metadata under
`../../lemma/python/*.dist-info/`.

## JavaScript packages

| Package | Version | Declared license |
|---|---:|---|
EOF
node - "$frontend_build/package-lock.json" >> "$notices" <<'JS'
const fs = require("fs");
const lock = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const packages = new Map();
for (const [location, metadata] of Object.entries(lock.packages ?? {})) {
  if (!location.includes("node_modules/") || !metadata.version) continue;
  const name = metadata.name ?? location.slice(location.lastIndexOf("node_modules/") + 13);
  const license = String(metadata.license ?? "See copied license text").replaceAll("|", "\\|");
  packages.set(`${name}@${metadata.version}`, { name, version: metadata.version, license });
}
const compare = (left, right) => left < right ? -1 : left > right ? 1 : 0;
for (const item of [...packages.values()].sort((left, right) =>
  compare(left.name, right.name) || compare(left.version, right.version))) {
  process.stdout.write(`| ${item.name} | ${item.version} | ${item.license} |\n`);
}
JS
cat >> "$notices" <<'EOF'

## Python packages

| Package | Version | Declared license |
|---|---:|---|
EOF
python3 - "$bundle/share/lemma/python" >> "$notices" <<'PY'
from email.parser import Parser
from pathlib import Path
import sys


def license_label(metadata) -> str:
    expression = metadata.get("License-Expression", "").strip()
    if expression:
        return expression
    declared = " ".join(metadata.get("License", "").split())
    if declared and len(declared) <= 120:
        return declared
    classifiers = [
        value.removeprefix("License ::").strip()
        for value in metadata.get_all("Classifier", [])
        if value.startswith("License ::")
    ]
    return "; ".join(classifiers) or "See installed package metadata"


packages = []
for metadata_path in Path(sys.argv[1]).glob("*.dist-info/METADATA"):
    metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8", errors="replace"))
    packages.append(
        (
            metadata.get("Name", metadata_path.parent.name),
            metadata.get("Version", "unknown"),
            license_label(metadata).replace("|", "\\|"),
        )
    )
for name, version, license_name in sorted(packages, key=lambda item: (item[0].casefold(), item[1])):
    print(f"| {name} | {version} | {license_name} |")
PY
cat >> "$notices" <<'EOF'

## Machine-readable inventory

`SBOM.cdx.json` is the CycloneDX 1.5 inventory generated from the exact npm lock
and the production Python requirements exported from `uv.lock`. The SBOM is part
of `manifest.sha256`, so a verified manifest also verifies this inventory.
EOF

sbom="$bundle/share/doc/lemma-linux/SBOM.cdx.json"
python3 -I -B "$SCRIPT_DIR/sbom.py" create \
  --package-lock "$frontend_build/package-lock.json" \
  --requirements "$requirements" \
  --application-version "$version" \
  --output "$sbom"

printf '%s\n' "$version" > "$bundle/VERSION"
printf '%s\n' "$python_abi" > "$bundle/PYTHON_ABI"
commit="$(git -C "$REPO_ROOT" rev-parse --verify HEAD 2>/dev/null || printf 'uncommitted')"
tree_state="clean"
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=normal 2>/dev/null)" ]]; then
  tree_state="dirty"
fi
cat > "$bundle/BUILD_INFO" <<EOF
version=$version
commit=$commit
source_tree=$tree_state
architecture=$release_arch
python_abi=$python_abi
node=$(node --version)
uv=$(uv --version)
source_date_epoch=$epoch
offline_build=true
minisign_signed=$([[ -n "$SIGNING_KEY" ]] && printf true || printf false)
EOF

# Secrets and mutable state must never enter an installation artifact. Vendored
# dependencies legitimately include public CA bundles such as certifi/cacert.pem, so
# credential-shaped filenames and private-key markers are forbidden in the
# project-owned source tree.
unexpected_path="$(find "$bundle" \( -type l -o \( ! -type d -a ! -type f \) \) \
  -print -quit)"
if [[ -n "$unexpected_path" ]]; then
  printf 'Refusing to package a link or special file: %s\n' "$unexpected_path" >&2
  exit 1
fi
unsafe_special_mode="$(find "$bundle" -mindepth 1 \( -type d -o -type f \) \
  -perm /7000 -print -quit)"
if [[ -n "$unsafe_special_mode" ]]; then
  printf 'Refusing to package a setuid, setgid, or sticky path: %s\n' \
    "$unsafe_special_mode" >&2
  exit 1
fi
invalid_bundle_path=""
while IFS= read -r -d '' relative_path; do
  relative_path="${relative_path#./}"
  if [[ ! "$relative_path" =~ ^[A-Za-z0-9._/+@=,:!~-]+$ || \
        "$relative_path" == ".." || "$relative_path" == ../* || \
        "$relative_path" == */../* || "$relative_path" == */.. ]]; then
    invalid_bundle_path="$relative_path"
    break
  fi
done < <(cd "$bundle" && find . -mindepth 1 -print0)
if [[ -n "$invalid_bundle_path" ]]; then
  printf 'Refusing a bundle path the installer cannot represent: %s\n' \
    "$invalid_bundle_path" >&2
  exit 1
fi
if find "$bundle" -type f \( -name '.env' -o -name 'app.db' \) -print -quit | grep -q .; then
  printf 'Refusing to package a secret or mutable data file.\n' >&2
  exit 1
fi
if find "$bundle/share/lemma/app" -type f \( -name '*.pem' -o -name '*.key' \
  -o -name '*.p12' -o -name '*.pfx' \) -print -quit | grep -q .; then
  printf 'Refusing to package a credential-shaped source file.\n' >&2
  exit 1
fi
# Scan project-owned sources, not vendored packages: third-party schemas may contain
# documentation placeholders that look like key headers. The expression is assembled
# from fragments so this scanner does not match its own source copy in the payload.
if ! python3 - "$bundle/share/lemma/app" <<'PY'
from pathlib import Path
import re
import sys


prefix = b"BEGIN "
suffix = b"PRIVATE" + b" KEY"
marker = re.compile(prefix + rb"(?:[A-Z0-9]+ )?" + suffix + b"|" + prefix + b"OPENSSH " + suffix)
for candidate in Path(sys.argv[1]).rglob("*"):
    if not candidate.is_file():
        continue
    try:
        content = candidate.read_bytes()
    except OSError as error:
        print(f"Could not scan {candidate}: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    if marker.search(content):
        print(f"Private-key marker found in {candidate}", file=sys.stderr)
        raise SystemExit(1)
PY
then
  printf 'Refusing to package private-key material.\n' >&2
  exit 1
fi

find "$bundle" -type d -exec chmod 755 {} +
find "$bundle" -type f -exec chmod go-w {} +
chmod 755 "$bundle/bin/lemma" "$bundle/bin/lemma-server" "$bundle/bin/lemma-doctor"
chmod 600 "$bundle/share/lemma/env.default"

printf '[5/6] Writing and verifying the release checksum manifest...\n'
(
  cd "$bundle"
  find . -type f ! -name manifest.sha256 -print0 | LC_ALL=C sort -z | \
    xargs -0 sha256sum > manifest.sha256
  sha256sum --check --strict --quiet manifest.sha256
)
if [[ -n "$SIGNING_KEY" ]]; then
  minisign -S -s "$SIGNING_KEY" -m "$bundle/manifest.sha256" \
    -x "$bundle/manifest.sha256.minisig" \
    -t "Lemma $version $release_arch bundle manifest"
  chmod 644 "$bundle/manifest.sha256.minisig"
fi

printf '[6/6] Creating the portable directory and archive...\n'
archive_temp="$work_dir/$bundle_name.tar.gz"
tar --sort=name --mtime="@$epoch" --owner=0 --group=0 --numeric-owner \
  -C "$work_dir" -cf - "$bundle_name" | gzip -n > "$archive_temp"
archive_hash="$(sha256sum "$archive_temp" | cut -d ' ' -f 1)"
printf '%s  %s\n' "$archive_hash" "$(basename "$archive")" \
  > "$work_dir/$bundle_name.tar.gz.sha256"
if [[ -n "$SIGNING_KEY" ]]; then
  minisign -S -s "$SIGNING_KEY" -m "$archive_temp" \
    -x "$work_dir/$bundle_name.tar.gz.minisig" \
    -t "Lemma $version $release_arch portable archive"
  chmod 644 "$work_dir/$bundle_name.tar.gz.minisig"
fi

# Publish only after every artifact is complete, so a failed compression cannot leave
# an apparently usable release directory in the requested output location.
mv -- "$bundle" "$final_dir"
mv -- "$archive_temp" "$archive"
mv -- "$work_dir/$bundle_name.tar.gz.sha256" "$archive_checksum"
if [[ -n "$SIGNING_KEY" ]]; then
  mv -- "$work_dir/$bundle_name.tar.gz.minisig" "$archive_signature"
fi

printf '\nLinux release ready:\n  %s\n  %s\n  %s\n' \
  "$final_dir" "$archive" "$archive_checksum"
if [[ -n "$SIGNING_KEY" ]]; then
  printf '  %s\n  %s\n' "$final_dir/manifest.sha256.minisig" "$archive_signature"
fi
printf 'Install with: %s/install.sh --bundle %q\n' "$final_dir" "$final_dir"

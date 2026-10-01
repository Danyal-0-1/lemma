#!/usr/bin/env bash
# Turn an already-built Lemma Linux bundle into a Debian binary package.
set -euo pipefail
umask 022
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PACKAGING_DIR="$SCRIPT_DIR/packaging/debian"
OUTPUT_DIR="$SCRIPT_DIR/dist"
BUNDLE_DIR=""
KEEP_WORK=0
VERIFY_KEY=""
SIGNING_KEY=""

usage() {
  cat <<'EOF'
Usage: ./linux_install/build-deb.sh --bundle DIRECTORY [options]

Convert a bundle previously produced by linux_install/build.sh into a native
Debian package. The bundle is verified and copied under /opt/lemma; this command
does not rebuild or download the vendored frontend or Python dependencies.

Options:
  --bundle DIRECTORY  Built lemma-VERSION-linux-ARCH directory (required)
  --output DIRECTORY  Destination directory (default: linux_install/dist)
  --keep-work          Retain the temporary package tree for inspection
  --minisign-public-key FILE
                       Require a valid signed bundle manifest from this trusted key
  --minisign-secret-key FILE
                       Create a detached minisign signature for the finished .deb
  -h, --help           Show this help
EOF
}

die() {
  printf 'build-deb.sh: ERROR: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --bundle)
      [[ $# -ge 2 ]] || die "missing value for --bundle"
      BUNDLE_DIR="$2"
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || die "missing value for --output"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --keep-work)
      KEEP_WORK=1
      shift
      ;;
    --minisign-public-key)
      [[ $# -ge 2 && -n "$2" ]] || die "missing value for --minisign-public-key"
      VERIFY_KEY="$2"
      shift 2
      ;;
    --minisign-secret-key)
      [[ $# -ge 2 && -n "$2" ]] || die "missing value for --minisign-secret-key"
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

[[ -n "$BUNDLE_DIR" ]] || {
  usage >&2
  die "--bundle is required"
}

[[ "$(uname -s)" == "Linux" ]] || \
  die "Debian packages must be assembled on Linux"

for command_name in awk chmod cp dirname dpkg-deb du find grep install ln \
  md5sum mktemp mv python3 realpath rm sed sha256sum sort stat touch uname xargs; do
  command -v "$command_name" >/dev/null 2>&1 || \
    die "required packaging command is unavailable: $command_name"
done
if [[ -n "$VERIFY_KEY" ]]; then
  command -v minisign >/dev/null 2>&1 || \
    die "minisign is required only when --minisign-public-key is used"
  [[ -f "$VERIFY_KEY" && ! -L "$VERIFY_KEY" ]] || \
    die "trusted minisign public key must be a regular, non-symbolic-link file"
  VERIFY_KEY="$(realpath -e -- "$VERIFY_KEY")"
fi
if [[ -n "$SIGNING_KEY" ]]; then
  command -v minisign >/dev/null 2>&1 || \
    die "minisign is required only when --minisign-secret-key is used"
  [[ -f "$SIGNING_KEY" && ! -L "$SIGNING_KEY" ]] || \
    die "minisign secret key must be a regular, non-symbolic-link file"
  SIGNING_KEY="$(realpath -e -- "$SIGNING_KEY")"
fi

[[ -d "$BUNDLE_DIR" ]] || die "bundle directory does not exist: $BUNDLE_DIR"
BUNDLE_DIR="$(cd "$BUNDLE_DIR" && pwd -P)"
[[ "$BUNDLE_DIR" != "/" ]] || die "refusing to package the filesystem root"

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
  share/lemma/env.default
  share/lemma/web/index.html
  share/applications/io.lemma.Lemma.desktop.in
  share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg
  share/metainfo/io.lemma.Lemma.metainfo.xml
  share/systemd/user/lemma.service.in
)
for relative_path in "${required_bundle_files[@]}"; do
  [[ -f "$BUNDLE_DIR/$relative_path" && ! -L "$BUNDLE_DIR/$relative_path" ]] || \
    die "bundle is missing a required regular file: $relative_path"
done
for required_directory in share/doc/lemma-linux/third-party/javascript \
  share/lemma/app/backend/app share/lemma/app/backend/migrations/versions \
  share/lemma/python share/lemma/web; do
  [[ -d "$BUNDLE_DIR/$required_directory" && \
     ! -L "$BUNDLE_DIR/$required_directory" ]] || \
    die "bundle is missing a required directory: $required_directory"
done
for executable_path in install.sh uninstall.sh bin/lemma bin/lemma-server \
  bin/lemma-doctor verify-release.sh; do
  [[ -x "$BUNDLE_DIR/$executable_path" ]] || \
    die "bundle launcher is not executable: $executable_path"
done

# build.sh deliberately emits a link-free tree. Recheck that invariant before
# checksum verification and copying so package contents cannot escape /opt/lemma.
unexpected_path="$(find "$BUNDLE_DIR" \( -type l -o \( ! -type d -a ! -type f \) \) \
  -print -quit)"
[[ -z "$unexpected_path" ]] || \
  die "bundle contains an unsupported link or special file: $unexpected_path"
unsafe_mode="$(find "$BUNDLE_DIR" -mindepth 1 \( -type d -o -type f \) \
  -perm /022 -print -quit)"
[[ -z "$unsafe_mode" ]] || \
  die "bundle contains a group- or world-writable path: $unsafe_mode"
unsafe_special_mode="$(find "$BUNDLE_DIR" -mindepth 1 \( -type d -o -type f \) \
  -perm /7000 -print -quit)"
[[ -z "$unsafe_special_mode" ]] || \
  die "bundle contains a setuid, setgid, or sticky path: $unsafe_special_mode"
for reserved_name in .lemma-install .lemma-install.next .lemma-install.previous; do
  [[ ! -e "$BUNDLE_DIR/$reserved_name" && ! -L "$BUNDLE_DIR/$reserved_name" ]] || \
    die "bundle contains reserved installer metadata: $reserved_name"
done

validate_relative_path() {
  local relative_path="$1"
  [[ -n "$relative_path" && "$relative_path" != /* ]] || return 1
  [[ "$relative_path" != "." && "$relative_path" != ".." ]] || return 1
  [[ "$relative_path" != ../* && "$relative_path" != */../* && \
     "$relative_path" != */.. ]] || return 1
  [[ "$relative_path" != *$'\n'* && "$relative_path" != *$'\r'* ]] || return 1
}

printf '[1/5] Verifying the release bundle...\n'
manifest_signature_count=0
if [[ -e "$BUNDLE_DIR/manifest.sha256.minisig" || \
      -L "$BUNDLE_DIR/manifest.sha256.minisig" ]]; then
  [[ -f "$BUNDLE_DIR/manifest.sha256.minisig" && \
     ! -L "$BUNDLE_DIR/manifest.sha256.minisig" ]] || \
    die "bundle manifest signature is not a regular file"
  manifest_signature_count=1
fi
if [[ -n "$VERIFY_KEY" ]]; then
  [[ "$manifest_signature_count" -eq 1 ]] || \
    die "--minisign-public-key requires manifest.sha256.minisig"
  minisign -V -q -p "$VERIFY_KEY" -m "$BUNDLE_DIR/manifest.sha256" \
    -x "$BUNDLE_DIR/manifest.sha256.minisig" || \
    die "bundle manifest signature verification failed"
elif [[ "$manifest_signature_count" -eq 1 ]]; then
  printf 'build-deb.sh: warning: bundle signature was not authenticated; use --minisign-public-key to require it\n' >&2
fi
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
  [[ -f "$BUNDLE_DIR/$relative_path" && \
     ! -L "$BUNDLE_DIR/$relative_path" ]] || \
    die "manifest.sha256 names a missing or unsafe file: $relative_path"
  manifest_paths["$relative_path"]=1
  manifest_count=$((manifest_count + 1))
done < "$BUNDLE_DIR/manifest.sha256"
((manifest_count > 0)) || die "manifest.sha256 is empty"

actual_file_count=0
while IFS= read -r -d '' relative_path; do
  relative_path="${relative_path#./}"
  validate_relative_path "$relative_path" || \
    die "bundle contains an unsafe file name"
  actual_file_count=$((actual_file_count + 1))
  if [[ "$relative_path" != "manifest.sha256" && \
        "$relative_path" != "manifest.sha256.minisig" && \
        -z "${manifest_paths[$relative_path]+present}" ]]; then
    die "bundle file is not covered by manifest.sha256: $relative_path"
  fi
done < <(cd "$BUNDLE_DIR" && \
  find . -mindepth 1 -type f -print0 | LC_ALL=C sort -z)
[[ "$actual_file_count" -eq $((manifest_count + 1 + manifest_signature_count)) ]] || \
  die "manifest.sha256 does not describe the complete bundle"

if ! (cd "$BUNDLE_DIR" && \
  sha256sum --check --strict --quiet manifest.sha256); then
  die "bundle checksum verification failed"
fi

mapfile -t version_lines < "$BUNDLE_DIR/VERSION"
[[ "${#version_lines[@]}" -eq 1 ]] || die "VERSION must contain exactly one line"
version="${version_lines[0]}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)*$ ]] || \
  die "unsupported bundle version: $version"
python3 -I -B "$BUNDLE_DIR/share/lemma/app/linux_install/sbom.py" validate \
  "$BUNDLE_DIR/share/doc/lemma-linux/SBOM.cdx.json" \
  --application-version "$version" || die "bundle SBOM validation failed"

mapfile -t python_lines < "$BUNDLE_DIR/PYTHON_ABI"
[[ "${#python_lines[@]}" -eq 1 ]] || \
  die "PYTHON_ABI must contain exactly one line"
python_abi="${python_lines[0]}"
[[ "$python_abi" =~ ^3\.([0-9]+)$ ]] || \
  die "unsupported Python ABI: $python_abi"
python_minor="${BASH_REMATCH[1]}"
((10#$python_minor >= 12)) || die "Python 3.12 or newer is required"

info_version=""
info_arch=""
info_python_abi=""
info_source_date_epoch=""
version_fields=0
arch_fields=0
python_fields=0
epoch_fields=0
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
    source_date_epoch)
      epoch_fields=$((epoch_fields + 1))
      info_source_date_epoch="$info_value"
      ;;
  esac
done < "$BUNDLE_DIR/BUILD_INFO"

[[ "$version_fields" -eq 1 && "$info_version" == "$version" ]] || \
  die "BUILD_INFO version does not match VERSION"
[[ "$python_fields" -eq 1 && "$info_python_abi" == "$python_abi" ]] || \
  die "BUILD_INFO Python ABI does not match PYTHON_ABI"
[[ "$arch_fields" -eq 1 ]] || \
  die "BUILD_INFO must contain exactly one architecture"
[[ "$epoch_fields" -le 1 ]] || \
  die "BUILD_INFO contains duplicate source_date_epoch fields"
if [[ "$epoch_fields" -eq 1 && \
      ! "$info_source_date_epoch" =~ ^[0-9]+$ ]]; then
  die "BUILD_INFO contains an invalid source_date_epoch"
fi

case "$info_arch" in
  x86_64) deb_arch="amd64" ;;
  aarch64) deb_arch="arm64" ;;
  *) die "unsupported bundle architecture: $info_arch" ;;
esac

# Debian sorts pre-release versions before the corresponding stable version when
# they use '~'. build.sh accepts SemVer-style '-', so translate only that marker;
# the application itself continues to see the original VERSION under /opt/lemma.
debian_version="${version//-/~}"
# The vendored native wheels are tied to one CPython minor ABI. Debian Python
# policy therefore calls for the versioned interpreter package, not a range on
# the python3 metapackage.
python_depends="python$python_abi"

[[ -f "$PACKAGING_DIR/control.in" && ! -L "$PACKAGING_DIR/control.in" ]] || \
  die "Debian control template is unavailable"
[[ -f "$PACKAGING_DIR/copyright" && ! -L "$PACKAGING_DIR/copyright" ]] || \
  die "Debian copyright metadata is unavailable"

install -d -m 755 -- "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"
case "$OUTPUT_DIR/" in
  "$BUNDLE_DIR/"*) die "output directory must not be inside the bundle" ;;
esac
deb_name="lemma_${debian_version}_${deb_arch}.deb"
deb_path="$OUTPUT_DIR/$deb_name"
checksum_path="$deb_path.sha256"
signature_path="$deb_path.minisig"
[[ ! -e "$deb_path" && ! -L "$deb_path" ]] || \
  die "output already exists; remove it explicitly before rebuilding: $deb_path"
[[ ! -e "$checksum_path" && ! -L "$checksum_path" ]] || \
  die "output already exists; remove it explicitly before rebuilding: $checksum_path"
if [[ -e "$signature_path" || -L "$signature_path" ]]; then
  die "output already exists; remove it explicitly before rebuilding: $signature_path"
fi

# Stage beside the destination so default builds can use filesystem reflinks for
# the large vendored payload and publishing the completed archives is atomic.
work_dir="$(mktemp -d "$OUTPUT_DIR/.lemma-deb-build.XXXXXXXX")"
cleanup() {
  if [[ "$KEEP_WORK" -eq 1 ]]; then
    printf 'Package work directory retained at %s\n' "$work_dir"
  else
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT

package_root="$work_dir/package"
install_root="$package_root/opt/lemma"
install -d -m 755 -- "$package_root/DEBIAN" "$install_root" \
  "$package_root/usr/bin" "$package_root/usr/lib/systemd/user" \
  "$package_root/usr/share/applications" \
  "$package_root/usr/share/icons/hicolor/scalable/apps" \
  "$package_root/usr/share/metainfo" "$package_root/usr/share/doc/lemma"

printf '[2/5] Staging the bundle once under /opt/lemma...\n'
# Reflinks keep the large vendored Python payload cheap while staging on a CoW
# filesystem; cp falls back to an ordinary copy without changing package output.
cp -a --reflink=auto -- "$BUNDLE_DIR/." "$install_root/"

for command_name in lemma lemma-server lemma-doctor; do
  ln -s -- "/opt/lemma/bin/$command_name" \
    "$package_root/usr/bin/$command_name"
done

printf '[3/5] Installing desktop and per-user service integration...\n'
desktop_template="$install_root/share/applications/io.lemma.Lemma.desktop.in"
service_template="$install_root/share/systemd/user/lemma.service.in"
grep -Fq '@LAUNCHER@' "$desktop_template" || \
  die "desktop template does not contain @LAUNCHER@"
grep -Fq '@INSTALL_ROOT@' "$service_template" || \
  die "service template does not contain @INSTALL_ROOT@"

sed 's|@LAUNCHER@|/usr/bin/lemma|g' "$desktop_template" > \
  "$package_root/usr/share/applications/io.lemma.Lemma.desktop"
sed 's|@INSTALL_ROOT@|/opt/lemma|g' "$service_template" > \
  "$package_root/usr/lib/systemd/user/lemma.service"
grep -Fq '@LAUNCHER@' \
  "$package_root/usr/share/applications/io.lemma.Lemma.desktop" && \
  die "desktop template rendering left an unresolved placeholder"
grep -Fq '@INSTALL_ROOT@' \
  "$package_root/usr/lib/systemd/user/lemma.service" && \
  die "service template rendering left an unresolved placeholder"

install -m 644 -- \
  "$install_root/share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg" \
  "$package_root/usr/share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg"
install -m 644 -- \
  "$install_root/share/metainfo/io.lemma.Lemma.metainfo.xml" \
  "$package_root/usr/share/metainfo/io.lemma.Lemma.metainfo.xml"
install -m 644 -- "$PACKAGING_DIR/copyright" \
  "$package_root/usr/share/doc/lemma/copyright"

# Keep packaged data readable but immutable to unprivileged users. The template
# contains no secrets and must be readable so lemma-server can create a private
# (0600) per-user copy on first launch.
find "$package_root" -type d -exec chmod 755 {} +
find "$package_root" -type f -exec chmod a+r,u+w,go-w,u-s,g-s,o-t {} +
chmod 755 "$install_root/bin/lemma" "$install_root/bin/lemma-server" \
  "$install_root/bin/lemma-doctor"
chmod 644 "$install_root/share/lemma/env.default" \
  "$package_root/usr/share/applications/io.lemma.Lemma.desktop" \
  "$package_root/usr/lib/systemd/user/lemma.service"

installed_size="$(du --apparent-size --block-size=1024 --summarize \
  "$package_root/opt" "$package_root/usr" | \
  awk '{ total += $1 } END { print total + 0 }')"
[[ "$installed_size" =~ ^[0-9]+$ ]] || die "could not calculate Installed-Size"

sed \
  -e "s|@VERSION@|$debian_version|g" \
  -e "s|@ARCHITECTURE@|$deb_arch|g" \
  -e "s|@INSTALLED_SIZE@|$installed_size|g" \
  -e "s|@PYTHON_DEPENDS@|$python_depends|g" \
  "$PACKAGING_DIR/control.in" > "$package_root/DEBIAN/control"
if grep -Eq '@[A-Z_]+@' "$package_root/DEBIAN/control"; then
  die "control template rendering left an unresolved placeholder"
fi
chmod 644 "$package_root/DEBIAN/control"

(
  cd "$package_root"
  find opt usr -type f -print0 | LC_ALL=C sort -z | \
    xargs -0 md5sum > DEBIAN/md5sums
)
chmod 644 "$package_root/DEBIAN/md5sums"

if [[ -n "${SOURCE_DATE_EPOCH:-}" ]]; then
  epoch="$SOURCE_DATE_EPOCH"
elif [[ "$epoch_fields" -eq 1 ]]; then
  epoch="$info_source_date_epoch"
else
  epoch="$(stat -c '%Y' "$BUNDLE_DIR/VERSION")"
fi
[[ "$epoch" =~ ^[0-9]+$ ]] || die "SOURCE_DATE_EPOCH must be a non-negative integer"
find "$package_root" -exec touch -h -d "@$epoch" {} +

printf '[4/5] Building the Debian archive...\n'
work_deb="$work_dir/$deb_name"
DPKG_DEB_THREADS_MAX=1 SOURCE_DATE_EPOCH="$epoch" \
  dpkg-deb --root-owner-group \
  --uniform-compression -Zxz -z9 --build "$package_root" "$work_deb"

[[ "$(dpkg-deb --field "$work_deb" Package)" == "lemma" ]] || \
  die "built package has the wrong package name"
[[ "$(dpkg-deb --field "$work_deb" Version)" == "$debian_version" ]] || \
  die "built package has the wrong version"
[[ "$(dpkg-deb --field "$work_deb" Architecture)" == "$deb_arch" ]] || \
  die "built package has the wrong architecture"

printf '[5/5] Writing the package checksum...\n'
(
  cd "$work_dir"
  sha256sum "$deb_name" > "$deb_name.sha256"
)
if [[ -n "$SIGNING_KEY" ]]; then
  minisign -S -s "$SIGNING_KEY" -m "$work_deb" \
    -x "$work_dir/$deb_name.minisig" \
    -t "Lemma $version $deb_arch Debian package"
  chmod 644 "$work_dir/$deb_name.minisig"
fi
mv -- "$work_deb" "$deb_path"
mv -- "$work_dir/$deb_name.sha256" "$checksum_path"
if [[ -n "$SIGNING_KEY" ]]; then
  mv -- "$work_dir/$deb_name.minisig" "$signature_path"
fi

printf '\nDebian package ready:\n  %s\n  %s\n' "$deb_path" "$checksum_path"
[[ -z "$SIGNING_KEY" ]] || printf '  %s\n' "$signature_path"
printf 'Install or upgrade with: sudo apt install %q\n' "$deb_path"

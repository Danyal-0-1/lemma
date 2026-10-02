# ─────────────────────────────────────────────────────────────────────────────
# test_linux_release.py — regression checks for the offline Linux distribution.
# READING ORDER: backend tests (after linux_install/README.md)
#
# Most checks are platform-neutral. The end-to-end installer exercise runs only on
# Linux because the production scripts intentionally depend on GNU userland tools.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import ast
import hashlib
import json
import os
import runpy
import stat
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from email.message import Message
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LINUX_ROOT = REPOSITORY_ROOT / "linux_install"
SHELL_SCRIPTS = (
    LINUX_ROOT / "build.sh",
    LINUX_ROOT / "build-deb.sh",
    LINUX_ROOT / "install.sh",
    LINUX_ROOT / "uninstall.sh",
    LINUX_ROOT / "verify-release.sh",
    LINUX_ROOT / "runtime" / "lemma",
    LINUX_ROOT / "runtime" / "lemma-server",
    LINUX_ROOT / "runtime" / "lemma-doctor",
)


def test_release_identity_is_synchronized() -> None:
    """A changed version must seed a fresh Linux backend tree on upgrade."""
    frontend_package = json.loads(
        (REPOSITORY_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    frontend_lock = json.loads(
        (REPOSITORY_ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    with (REPOSITORY_ROOT / "backend" / "pyproject.toml").open("rb") as handle:
        backend_project = tomllib.load(handle)
    with (REPOSITORY_ROOT / "backend" / "uv.lock").open("rb") as handle:
        backend_lock = tomllib.load(handle)

    main_tree = ast.parse(
        (REPOSITORY_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    )
    server_version = next(
        statement.value.value
        for statement in main_tree.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SERVER_VERSION"
            for target in statement.targets
        )
        and isinstance(statement.value, ast.Constant)
    )
    locked_backend = next(
        package
        for package in backend_lock["package"]
        if package["name"] == backend_project["project"]["name"]
    )
    metainfo = ET.parse(
        REPOSITORY_ROOT / "linux_install" / "assets" / "io.lemma.Lemma.metainfo.xml"
    )
    advertised_versions = [
        release.attrib["version"] for release in metainfo.findall("./releases/release")
    ]

    expected = frontend_package["version"]
    assert expected == "0.3.0"
    assert frontend_lock["version"] == expected
    assert frontend_lock["packages"][""]["version"] == expected
    assert backend_project["project"]["version"] == expected
    assert locked_backend["version"] == expected
    assert server_version == expected
    assert advertised_versions[0] == expected


def test_assurance_dependencies_feed_the_offline_bundle() -> None:
    """PDF/form ingestion must be lock-backed and exported into the vendored runtime."""
    with (REPOSITORY_ROOT / "backend" / "uv.lock").open("rb") as handle:
        backend_lock = tomllib.load(handle)
    packages = {package["name"]: package for package in backend_lock["package"]}
    application_dependencies = {
        dependency["name"] for dependency in packages["lemma-backend"]["dependencies"]
    }

    for name in ("pypdf", "python-multipart"):
        assert name in application_dependencies
        assert packages[name]["wheels"]

    builder = (LINUX_ROOT / "build.sh").read_text(encoding="utf-8")
    assert "uv export" in builder
    assert "--no-dev --no-emit-project" in builder
    assert 'uv pip install --target "$bundle/share/lemma/python"' in builder
    assert "--offline --no-python-downloads" in builder


def test_linux_shell_entrypoints_are_executable_and_parse() -> None:
    """Keep release entrypoints directly runnable and valid Bash programs."""
    for script in SHELL_SCRIPTS:
        assert script.is_file(), script
        assert os.access(script, os.X_OK), script
        result = subprocess.run(
            ["bash", "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"


def test_linux_supervisor_keeps_bash_43_wait_compatibility() -> None:
    """Do not accidentally require Bash 5.1's PID-list form of ``wait -n``."""
    supervisor = (LINUX_ROOT / "runtime" / "lemma-server").read_text()
    assert "wait -n\n" in supervisor
    assert 'wait -n "$frontend_pid" "$backend_pid"' not in supervisor


def test_linux_templates_retain_their_render_markers() -> None:
    """Prevent a source edit from silently breaking installer path rendering."""
    desktop = (LINUX_ROOT / "assets" / "io.lemma.Lemma.desktop.in").read_text()
    service = (LINUX_ROOT / "assets" / "lemma.service.in").read_text()
    assert "@LAUNCHER@" in desktop
    assert "@INSTALL_ROOT@" in service


def test_linux_configuration_exposes_local_model_attestation_safely() -> None:
    """Installed local-only projects need the same explicit model attestation knob."""
    defaults = (LINUX_ROOT / "assets" / "env.default").read_text(encoding="utf-8")
    assert "MOCK_LLM=true" in defaults
    assert "ENABLE_HOST_EXECUTION=false" in defaults
    assert "LEMMA_ENABLE_HEADLESS_CODING=false" in defaults
    assert "LEMMA_LOCAL_MODEL_IDS=" in defaults
    assert "GEMINI_API_KEY=" in defaults
    assert "LEMMA_OLLAMA_BASE_URL=http://127.0.0.1:11434" in defaults
    assert "LEMMA_CUSTOM_OPENAI_BASE_URL=" in defaults
    assert "LEMMA_CODEX_EXECUTABLE=" in defaults
    assert "LEMMA_CLAUDE_EXECUTABLE=" in defaults
    assert "LEMMA_GEMINI_EXECUTABLE=" in defaults


def test_packaged_capsule_verifier_runs_without_server_or_database(tmp_path: Path) -> None:
    """The installed runner must expose the pure verifier in isolated Python mode."""
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    runner = LINUX_ROOT / "runtime" / "research_capsule_runner.py"
    base_command = [
        sys.executable,
        "-I",
        "-B",
        str(runner),
        "--backend",
        str(REPOSITORY_ROOT / "backend"),
        "--vendor",
        str(vendor),
        "--",
        "verify",
    ]

    help_result = subprocess.run(
        base_command + ["--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "usage:" in help_result.stdout
    assert "verify" in help_result.stdout

    project_id = "00000000-0000-0000-0000-000000000001"
    manifest = {
        "project": {"id": project_id},
        "policy": {"project_id": project_id},
        "sources": [],
        "excerpts": [],
        "claims": [],
        "claim_evidence": [],
        "protocols": [],
        "tasks": [],
        "runs": [],
        "findings": [],
        "results": [],
        "source_links": [],
        "model_calls": [],
        "finding_reviews": [],
        "dependencies": [],
        "meetings": [],
        "outcomes": [],
        "actions": [],
        "trace_links": [],
        "activity": [],
        "task_assurance": [],
        "assurance_acceptances": [],
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    valid_capsule = tmp_path / "valid.json"
    valid_capsule.write_text(
        json.dumps(
            {
                "format": "lemma.research-capsule.v1",
                "hash_algorithm": "sha256",
                "project_id": project_id,
                "manifest": manifest,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    valid_result = subprocess.run(
        base_command + [str(valid_capsule)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr
    assert json.loads(valid_result.stdout)["valid"] is True

    invalid_capsule = tmp_path / "invalid.json"
    invalid_capsule.write_text("not JSON\n", encoding="utf-8")
    invalid_result = subprocess.run(
        base_command + [str(invalid_capsule)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid_result.returncode == 2
    assert '"valid": false' in invalid_result.stdout


def test_research_assurance_payload_is_mandatory_in_linux_artifacts() -> None:
    """Portable and Debian installers must reject a partial assurance pipeline."""
    required_paths = (
        "libexec/research_capsule_runner.py",
        "share/lemma/app/backend/app/lab/assurance.py",
        "share/lemma/app/backend/app/lab/governance.py",
        "share/lemma/app/backend/app/lab/integrity.py",
        "share/lemma/app/backend/app/lab/research_capsule.py",
        "share/lemma/app/backend/app/lab/source_import.py",
        "share/lemma/app/backend/app/lab/source_routes.py",
        "share/lemma/app/backend/alembic.ini",
        "share/lemma/app/backend/migrations/versions/0003_research_assurance.py",
        "share/lemma/app/backend/migrations/versions/0004_research_assurance_hardening.py",
        "share/lemma/app/backend/migrations/versions/0005_model_connections.py",
        "share/lemma/app/backend/migrations/versions",
    )
    for script_name in ("build.sh", "build-deb.sh", "install.sh"):
        script = (LINUX_ROOT / script_name).read_text(encoding="utf-8")
        for required_path in required_paths:
            assert required_path in script, f"{script_name} does not require {required_path}"

    launcher = (LINUX_ROOT / "runtime" / "lemma").read_text(encoding="utf-8")
    assert "verify-capsule" in launcher
    assert "research_capsule_runner.py" in launcher
    doctor = (LINUX_ROOT / "runtime" / "lemma-doctor").read_text(encoding="utf-8")
    assert "offline research capsule verifier" in doctor


def test_release_sbom_is_deterministic_and_lock_derived(tmp_path: Path) -> None:
    """Inventory both dependency ecosystems without network or time-dependent data."""
    package_lock = tmp_path / "package-lock.json"
    requirements = tmp_path / "requirements.txt"
    first_output = tmp_path / "first.cdx.json"
    second_output = tmp_path / "second.cdx.json"
    package_lock.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "lemma-frontend", "version": "0.3.0"},
                    "node_modules/@example/widget": {
                        "version": "1.2.3",
                        "license": "MIT",
                        "integrity": "sha256-YWJj",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    requirements.write_text(
        "Example_Python==4.5.6 \\\n"
        "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "    # via lemma-backend\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-I",
        "-B",
        str(LINUX_ROOT / "sbom.py"),
        "create",
        "--package-lock",
        str(package_lock),
        "--requirements",
        str(requirements),
        "--application-version",
        "0.3.0",
    ]
    subprocess.run(command + ["--output", str(first_output)], check=True)
    subprocess.run(command + ["--output", str(second_output)], check=True)
    assert first_output.read_bytes() == second_output.read_bytes()

    document = json.loads(first_output.read_text(encoding="utf-8"))
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    assert [component["purl"] for component in document["components"]] == [
        "pkg:npm/%40example/widget@1.2.3",
        "pkg:pypi/example-python@4.5.6",
    ]
    assert "timestamp" not in document["metadata"]
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(LINUX_ROOT / "sbom.py"),
            "validate",
            str(first_output),
            "--application-version",
            "0.3.0",
        ],
        check=True,
    )


def test_release_signing_is_explicit_and_optional() -> None:
    """Keep key use opt-in and expose verification consistently at each boundary."""
    build_help = subprocess.run(
        [str(LINUX_ROOT / "build.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    deb_help = subprocess.run(
        [str(LINUX_ROOT / "build-deb.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    install_help = subprocess.run(
        [str(LINUX_ROOT / "install.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    verify_help = subprocess.run(
        [str(LINUX_ROOT / "verify-release.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "--minisign-secret-key" in build_help
    assert "--minisign-public-key" in deb_help
    assert "--minisign-secret-key" in deb_help
    assert "--minisign-public-key" in install_help
    assert "--public-key" in verify_help


def test_packaged_frontend_trusts_only_advertised_loopback_hosts() -> None:
    """Keep localhost usable without reopening the static server to DNS rebinding."""
    namespace = runpy.run_path(str(LINUX_ROOT / "runtime" / "frontend_server.py"))
    handler_class = namespace["LemmaHandler"]
    security_headers = namespace["SECURITY_HEADERS"]
    connect_policy = security_headers["Content-Security-Policy"]
    assert "http://127.0.0.1:8000" in connect_policy
    assert "http://localhost:8000" in connect_policy
    assert "ws://127.0.0.1:8000" in connect_policy
    assert "ws://localhost:8000" in connect_policy

    handler = object.__new__(handler_class)
    handler.headers = Message()
    handler.headers["Host"] = "localhost:5173"
    assert handler._host_is_allowed()
    handler.headers.replace_header("Host", "example.com:5173")
    assert not handler._host_is_allowed()


def _write(bundle: Path, relative_path: str, content: str, mode: int = 0o644) -> None:
    """Create one fixture file with release-compatible permissions."""
    destination = bundle / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    destination.write_text(content, encoding="utf-8")
    destination.chmod(mode)


def _fixture_bundle(bundle: Path) -> None:
    """Build the smallest complete bundle accepted by the portable installer."""
    machine = os.uname().machine
    architecture = {
        "amd64": "x86_64",
        "arm64": "aarch64",
        "x86_64": "x86_64",
        "aarch64": "aarch64",
    }.get(machine, machine)
    bundle.mkdir(mode=0o755)
    _write(bundle, "VERSION", "0.3.0\n")
    _write(bundle, "PYTHON_ABI", f"{sys.version_info.major}.{sys.version_info.minor}\n")
    _write(
        bundle,
        "BUILD_INFO",
        f"version=0.3.0\narchitecture={architecture}\n"
        f"python_abi={sys.version_info.major}.{sys.version_info.minor}\n",
    )
    _write(bundle, "install.sh", (LINUX_ROOT / "install.sh").read_text(), 0o755)
    _write(bundle, "uninstall.sh", (LINUX_ROOT / "uninstall.sh").read_text(), 0o755)
    _write(bundle, "bin/lemma", (LINUX_ROOT / "runtime" / "lemma").read_text(), 0o755)
    for command_name in ("lemma-server", "lemma-doctor"):
        _write(bundle, f"bin/{command_name}", "#!/usr/bin/env bash\nexit 0\n", 0o755)
    _write(bundle, "libexec/backend_runner.py", "# fixture\n")
    _write(bundle, "libexec/frontend_server.py", "# fixture\n")
    _write(
        bundle,
        "libexec/research_capsule_runner.py",
        (LINUX_ROOT / "runtime" / "research_capsule_runner.py").read_text(),
    )
    _write(bundle, "verify-release.sh", (LINUX_ROOT / "verify-release.sh").read_text(), 0o755)
    _write(
        bundle,
        "share/lemma/app/linux_install/sbom.py",
        (LINUX_ROOT / "sbom.py").read_text(),
    )
    fixture_components = [
        {
            "type": "library",
            "bom-ref": "pkg:npm/example-js@1.0.0",
            "name": "example-js",
            "version": "1.0.0",
            "purl": "pkg:npm/example-js@1.0.0",
            "properties": [{"name": "lemma:ecosystem", "value": "javascript"}],
        },
        {
            "type": "library",
            "bom-ref": "pkg:pypi/example-python@1.0.0",
            "name": "example-python",
            "version": "1.0.0",
            "purl": "pkg:pypi/example-python@1.0.0",
            "properties": [{"name": "lemma:ecosystem", "value": "python"}],
        },
    ]
    root_reference = "pkg:generic/lemma@0.3.0"
    fixture_sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": root_reference,
                "name": "lemma",
                "version": "0.3.0",
                "purl": root_reference,
            }
        },
        "components": fixture_components,
        "dependencies": [
            {
                "ref": root_reference,
                "dependsOn": [component["bom-ref"] for component in fixture_components],
            }
        ],
    }
    _write(
        bundle,
        "share/doc/lemma-linux/SBOM.cdx.json",
        json.dumps(fixture_sbom, indent=2, sort_keys=True) + "\n",
    )
    _write(bundle, "share/doc/lemma-linux/THIRD_PARTY_NOTICES.md", "# Notices\n")
    _write(bundle, "share/lemma/env.default", "MOCK_LLM=true\n", 0o600)
    _write(bundle, "share/lemma/web/index.html", '<div id="root"></div>\n')
    _write(bundle, "share/lemma/transition/old.txt", "old layout\n")
    _write(bundle, "share/lemma/app/backend/app/__init__.py", "")
    _write(bundle, "share/lemma/app/backend/app/lab/__init__.py", "")
    for module_name in ("assurance", "governance", "source_import", "source_routes"):
        _write(bundle, f"share/lemma/app/backend/app/lab/{module_name}.py", "# fixture\n")
    _write(
        bundle,
        "share/lemma/app/backend/app/lab/integrity.py",
        (REPOSITORY_ROOT / "backend" / "app" / "lab" / "integrity.py").read_text(),
    )
    _write(
        bundle,
        "share/lemma/app/backend/app/lab/research_capsule.py",
        (REPOSITORY_ROOT / "backend" / "app" / "lab" / "research_capsule.py").read_text(),
    )
    _write(bundle, "share/lemma/app/backend/alembic.ini", "[alembic]\n")
    _write(
        bundle,
        "share/lemma/app/backend/migrations/versions/0003_research_assurance.py",
        (
            REPOSITORY_ROOT
            / "backend"
            / "migrations"
            / "versions"
            / "0003_research_assurance.py"
        ).read_text(),
    )
    _write(
        bundle,
        "share/lemma/app/backend/migrations/versions/0004_research_assurance_hardening.py",
        (
            REPOSITORY_ROOT
            / "backend"
            / "migrations"
            / "versions"
            / "0004_research_assurance_hardening.py"
        ).read_text(),
    )
    _write(
        bundle,
        "share/lemma/app/backend/migrations/versions/0005_model_connections.py",
        (
            REPOSITORY_ROOT
            / "backend"
            / "migrations"
            / "versions"
            / "0005_model_connections.py"
        ).read_text(),
    )
    _write(bundle, "share/lemma/python/.keep", "")
    _write(bundle, "share/doc/lemma-linux/third-party/javascript/.keep", "")
    _write(
        bundle,
        "share/applications/io.lemma.Lemma.desktop.in",
        "[Desktop Entry]\nType=Application\nExec=@LAUNCHER@ open\n",
    )
    _write(bundle, "share/icons/hicolor/scalable/apps/io.lemma.Lemma.svg", "<svg/>\n")
    _write(bundle, "share/metainfo/io.lemma.Lemma.metainfo.xml", "<component/>\n")
    _write(
        bundle,
        "share/systemd/user/lemma.service.in",
        "[Service]\nExecStart=@INSTALL_ROOT@/bin/lemma-server\n",
    )

    _write_manifest(bundle)


def _write_manifest(bundle: Path) -> None:
    """Regenerate the complete fixture manifest after an upgrade edit."""
    entries: list[str] = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        if path.name in {"manifest.sha256", "manifest.sha256.minisig"}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  ./{path.relative_to(bundle)}")
    _write(bundle, "manifest.sha256", "\n".join(entries) + "\n")


@pytest.mark.skipif(sys.platform != "linux", reason="installer requires GNU/Linux")
def test_portable_install_and_uninstall_round_trip(tmp_path: Path) -> None:
    """Install a verified fixture, render integrations, and remove only owned files."""
    bundle = tmp_path / "bundle"
    prefix = tmp_path / "installed-lemma"
    home = tmp_path / "home"
    data_home = tmp_path / "xdg-data"
    config_home = tmp_path / "xdg-config"
    state_home = tmp_path / "xdg-state"
    home.mkdir(mode=0o755)
    _fixture_bundle(bundle)

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_STATE_HOME": str(state_home),
            "LEMMA_PYTHON": sys.executable,
        }
    )

    unsafe_bundle = tmp_path / "unsafe-bundle"
    _fixture_bundle(unsafe_bundle)
    (unsafe_bundle / "bin/lemma").chmod(0o4755)
    unsafe_result = subprocess.run(
        [
            str(LINUX_ROOT / "install.sh"),
            "--bundle",
            str(unsafe_bundle),
            "--prefix",
            str(tmp_path / "unsafe-install"),
        ],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert unsafe_result.returncode != 0
    assert "setuid, setgid, or sticky" in unsafe_result.stderr

    overlapping_environment = environment | {"XDG_CONFIG_HOME": str(data_home)}
    overlap_result = subprocess.run(
        [
            str(LINUX_ROOT / "install.sh"),
            "--bundle",
            str(bundle),
            "--prefix",
            str(tmp_path / "overlap-install"),
        ],
        check=False,
        env=overlapping_environment,
        capture_output=True,
        text=True,
    )
    assert overlap_result.returncode != 0
    assert "mutable user-data paths must not overlap" in overlap_result.stderr

    subprocess.run(
        [str(LINUX_ROOT / "install.sh"), "--bundle", str(bundle), "--prefix", str(prefix)],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert (prefix / ".lemma-install" / "installed-files").is_file()
    assert (home / ".local/bin/lemma").is_symlink()
    assert os.readlink(home / ".local/bin/lemma") == str(prefix / "bin/lemma")
    assert (
        str(prefix / "bin/lemma") in (data_home / "applications/io.lemma.Lemma.desktop").read_text()
    )
    assert str(prefix) in (data_home / "systemd/user/lemma.service").read_text()
    assert stat.S_IMODE((prefix / "share/lemma/env.default").stat().st_mode) == 0o600
    assert not (prefix / ".lemma-install.next").exists()
    assert not (prefix / ".lemma-install.previous").exists()

    verifier_help = subprocess.run(
        [str(prefix / "bin/lemma"), "verify-capsule", "--help"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert verifier_help.returncode == 0, verifier_help.stderr
    assert "usage:" in verifier_help.stdout

    _write(bundle, "share/lemma/web/index.html", '<div id="root">upgraded</div>\n')
    (bundle / "share/lemma/transition/old.txt").unlink()
    (bundle / "share/lemma/transition").rmdir()
    _write(bundle, "share/lemma/transition", "new layout\n")
    _write_manifest(bundle)
    subprocess.run(
        [str(LINUX_ROOT / "install.sh"), "--bundle", str(bundle), "--prefix", str(prefix)],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert "upgraded" in (prefix / "share/lemma/web/index.html").read_text()
    assert (prefix / "share/lemma/transition").read_text() == "new layout\n"
    assert not (prefix / ".lemma-install.next").exists()
    assert not (prefix / ".lemma-install.previous").exists()

    preserved = data_home / "lemma" / "keep.txt"
    preserved.parent.mkdir(parents=True, mode=0o700)
    preserved.write_text("research state\n", encoding="utf-8")
    _write(prefix, "bin/lemma", "#!/usr/bin/env bash\nexit 1\n", 0o755)
    purge_result = subprocess.run(
        [str(prefix / "uninstall.sh"), "--purge", "data"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert purge_result.returncode != 0
    assert "refusing to purge live mutable data" in purge_result.stderr
    assert preserved.read_text(encoding="utf-8") == "research state\n"

    subprocess.run(
        [str(prefix / "uninstall.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert not prefix.exists()
    assert not (home / ".local/bin/lemma").exists()
    assert not (data_home / "applications/io.lemma.Lemma.desktop").exists()
    assert preserved.read_text(encoding="utf-8") == "research state\n"

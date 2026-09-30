# ─────────────────────────────────────────────────────────────────────────────
# test_linux_release.py — regression checks for the offline Linux distribution.
# READING ORDER: backend tests (after linux_install/README.md)
#
# Most checks are platform-neutral. The end-to-end installer exercise runs only on
# Linux because the production scripts intentionally depend on GNU userland tools.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import hashlib
import os
import runpy
import stat
import subprocess
import sys
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
    LINUX_ROOT / "runtime" / "lemma",
    LINUX_ROOT / "runtime" / "lemma-server",
    LINUX_ROOT / "runtime" / "lemma-doctor",
)


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
    _write(bundle, "VERSION", "0.2.0\n")
    _write(bundle, "PYTHON_ABI", f"{sys.version_info.major}.{sys.version_info.minor}\n")
    _write(
        bundle,
        "BUILD_INFO",
        f"version=0.2.0\narchitecture={architecture}\n"
        f"python_abi={sys.version_info.major}.{sys.version_info.minor}\n",
    )
    _write(bundle, "install.sh", (LINUX_ROOT / "install.sh").read_text(), 0o755)
    _write(bundle, "uninstall.sh", (LINUX_ROOT / "uninstall.sh").read_text(), 0o755)
    for command_name in ("lemma", "lemma-server", "lemma-doctor"):
        _write(bundle, f"bin/{command_name}", "#!/usr/bin/env bash\nexit 0\n", 0o755)
    _write(bundle, "libexec/backend_runner.py", "# fixture\n")
    _write(bundle, "libexec/frontend_server.py", "# fixture\n")
    _write(bundle, "share/doc/lemma-linux/THIRD_PARTY_NOTICES.md", "# Notices\n")
    _write(bundle, "share/lemma/env.default", "MOCK_LLM=true\n", 0o600)
    _write(bundle, "share/lemma/web/index.html", '<div id="root"></div>\n')
    _write(bundle, "share/lemma/transition/old.txt", "old layout\n")
    _write(bundle, "share/lemma/app/backend/app/__init__.py", "")
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
        if path.name == "manifest.sha256":
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
    assert str(prefix / "bin/lemma") in (
        data_home / "applications/io.lemma.Lemma.desktop"
    ).read_text()
    assert str(prefix) in (data_home / "systemd/user/lemma.service").read_text()
    assert stat.S_IMODE((prefix / "share/lemma/env.default").stat().st_mode) == 0o600
    assert not (prefix / ".lemma-install.next").exists()
    assert not (prefix / ".lemma-install.previous").exists()

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

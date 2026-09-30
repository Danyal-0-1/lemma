"""Bounded, workspace-confined Git operations for the local IDE.

Read-only status and diff operations are safe while host tools are locked.  The HTTP
layer separately gates stage, unstage, commit, and push behind the operator's explicit
``ENABLE_HOST_EXECUTION`` opt-in.  Every command is fixed argv, literal-pathspec only,
non-interactive, hook/signing disabled, and time/output bounded by ``git_capture``.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from app.workspaces import github
from app.workspaces.files import is_available_path
from app.workspaces.gitutil import GitResult, git_capture

MAX_MUTATION_PATHS = 500
MAX_PATH_CHARS = 2_048
MAX_COMMIT_MESSAGE_CHARS = 5_000
MAX_PATCH_BYTES = 1_000_000
MAX_PUBLIC_OUTPUT_CHARS = 8_000

_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SCP_REMOTE_RE = re.compile(
    r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?:[^\s]+$"
)
_GITHUB_PART_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
_GITHUB_SCP_RE = re.compile(
    r"^git@github\.com:(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]{0,99})/"
    r"(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]{0,99}?)(?:\.git)?$",
    re.IGNORECASE,
)
_CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


class SourceControlError(ValueError):
    """A safe, user-facing source-control failure."""


def _root(path: str) -> Path:
    root = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise SourceControlError("workspace directory is unavailable")
    return root


def _public_output(value: str, secret_url: str | None = None) -> str:
    """Keep Git diagnostics useful without echoing credentials or remote URLs."""
    cleaned = value.replace("\x00", "")
    cleaned = re.sub(r"(?i)(https?://)[^/@\s]+(?::[^/@\s]*)?@", r"\1", cleaned)
    if secret_url:
        cleaned = cleaned.replace(secret_url, "[configured remote]")
    return cleaned.strip()[:MAX_PUBLIC_OUTPUT_CHARS]


def _failure(result: GitResult, fallback: str, *, secret_url: str | None = None) -> None:
    if result.timed_out:
        raise SourceControlError(f"{fallback}: Git timed out")
    detail = _public_output(result.output, secret_url)
    raise SourceControlError(f"{fallback}: {detail or 'Git returned an error'}")


def _capture(root: Path, args: list[str], *, max_bytes: int = MAX_PUBLIC_OUTPUT_CHARS) -> GitResult:
    return git_capture(args, root, max_output_bytes=max_bytes)


def _query(root: Path, args: list[str], fallback: str) -> str:
    result = _capture(root, args)
    if result.returncode != 0 or result.timed_out:
        _failure(result, fallback)
    return result.output.strip()


def _validated_github_remote_url(url: str) -> tuple[str, dict[str, object]]:
    """Accept only a credential-free github.com repository URL and normalize it."""
    if (
        not url
        or len(url) > 2_048
        or any(ord(character) < 32 for character in url)
        or "%" in url
    ):
        raise SourceControlError("GitHub remote URL is invalid")

    scp = _GITHUB_SCP_RE.fullmatch(url)
    if scp:
        owner, repository = scp.group("owner", "repo")
        if not _GITHUB_PART_RE.fullmatch(owner) or not _GITHUB_PART_RE.fullmatch(repository):
            raise SourceControlError("GitHub owner or repository name is invalid")
        normalized = f"git@github.com:{owner}/{repository}.git"
        return normalized, {
            "provider": "github",
            "host": github.GITHUB_HOST,
            "owner": owner,
            "repository": repository,
            "protocol": "ssh",
            "display": f"github.com/{owner}/{repository}",
            "credentials_embedded": False,
        }

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SourceControlError("GitHub remote URL is invalid") from error
    if (
        parsed.scheme not in {"https", "ssh"}
        or parsed.hostname is None
        or parsed.hostname.lower() != github.GITHUB_HOST
        or parsed.query
        or parsed.fragment
    ):
        raise SourceControlError("remote must be an HTTPS or SSH github.com repository URL")
    if parsed.scheme == "https":
        if parsed.username is not None or parsed.password is not None or port not in {None, 443}:
            raise SourceControlError("credentials and custom ports are not accepted in GitHub URLs")
    elif parsed.username != "git" or parsed.password is not None or port not in {None, 22}:
        raise SourceControlError("SSH GitHub URLs must use the git user and default SSH port")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise SourceControlError("GitHub remote URL must identify exactly one owner and repository")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not _GITHUB_PART_RE.fullmatch(owner) or not _GITHUB_PART_RE.fullmatch(repository):
        raise SourceControlError("GitHub owner or repository name is invalid")
    if parsed.scheme == "https":
        normalized = f"https://github.com/{owner}/{repository}.git"
    else:
        normalized = f"ssh://git@github.com/{owner}/{repository}.git"
    return normalized, {
        "provider": "github",
        "host": github.GITHUB_HOST,
        "owner": owner,
        "repository": repository,
        "protocol": parsed.scheme,
        "display": f"github.com/{owner}/{repository}",
        "credentials_embedded": False,
    }


def _public_remote_metadata(url: str) -> dict[str, object]:
    """Describe a remote without ever returning its URL or embedded credentials."""
    try:
        _, details = _validated_github_remote_url(url)
        return {**details, "valid": True}
    except SourceControlError:
        pass

    protocol: str | None = None
    host: str | None = None
    display: str | None = None
    credentials_embedded = False
    if "://" not in url and _SCP_REMOTE_RE.fullmatch(url):
        authority, path = url.split(":", 1)
        host = authority.rsplit("@", 1)[-1].lower()
        protocol = "ssh"
        display = f"{host}/{path.removesuffix('.git')}"[:512]
    else:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname.lower() if parsed.hostname else None
            protocol = parsed.scheme.lower() or None
            credentials_embedded = parsed.username is not None or parsed.password is not None
            if host:
                display = f"{host}{parsed.path.removesuffix('.git')}"[:512]
        except ValueError:
            pass
    return {
        "provider": "github" if host == github.GITHUB_HOST else "other",
        "host": host,
        "owner": None,
        "repository": None,
        "protocol": protocol,
        "display": display,
        "credentials_embedded": credentials_embedded,
        "valid": False,
    }


def _safe_status_path(root: Path, rel: str, *, require_exists: bool = False) -> str:
    """Validate a Git path lexically and through any existing parent symlinks."""
    if (
        not is_available_path(rel)
        or len(rel) > MAX_PATH_CHARS
        or any(ord(character) < 32 for character in rel)
    ):
        raise SourceControlError("a selected path is not available")

    target = root / rel
    parent = target.parent.resolve(strict=False)
    if not parent.is_relative_to(root):
        raise SourceControlError("a selected path escapes the workspace")
    if target.is_symlink():
        raise SourceControlError("symbolic-link paths cannot be changed from the UI")
    if target.exists():
        resolved = target.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise SourceControlError("a selected path escapes the workspace")
    elif require_exists:
        raise SourceControlError("a selected path no longer exists")
    return rel


def _validated_paths(root: Path, paths: list[str]) -> list[str]:
    if not paths or len(paths) > MAX_MUTATION_PATHS:
        raise SourceControlError(f"select between 1 and {MAX_MUTATION_PATHS} paths")
    validated: list[str] = []
    seen: set[str] = set()
    for path in paths:
        safe = _safe_status_path(root, path)
        if safe not in seen:
            validated.append(safe)
            seen.add(safe)
    return validated


def _change_label(code: str, conflict: bool = False) -> str:
    if conflict:
        return "conflict"
    return {
        "?": "untracked",
        "A": "added",
        "C": "copied",
        "D": "deleted",
        "M": "modified",
        "R": "renamed",
        "T": "type changed",
        "U": "conflict",
    }.get(code, "changed")


def _parse_porcelain(root: Path, raw: str) -> list[dict[str, object]]:
    """Parse ``git status --porcelain=v1 -z``, including rename/copy pairs."""
    fields = raw.split("\x00")
    changes: list[dict[str, object]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry or len(entry) < 4:
            continue
        x, y = entry[0], entry[1]
        path = entry[3:]
        original: str | None = None
        if x in {"R", "C"} or y in {"R", "C"}:
            # With -z Git emits destination first and original path as the next field.
            if index < len(fields):
                original = fields[index] or None
                index += 1
        try:
            safe_path = _safe_status_path(root, path)
        except SourceControlError:
            continue
        if original:
            try:
                original = _safe_status_path(root, original)
            except SourceControlError:
                original = None

        pair = f"{x}{y}"
        conflict = pair in _CONFLICT_CODES
        base = {
            "path": safe_path,
            "original_path": original,
            "index": x,
            "working_tree": y,
            "conflict": conflict,
        }
        if pair == "??":
            changes.append({**base, "staged": False, "status": "untracked"})
            continue
        if conflict:
            changes.append({**base, "staged": False, "status": "conflict"})
            continue
        if x not in {" ", "!", "?"}:
            changes.append({**base, "staged": True, "status": _change_label(x)})
        if y not in {" ", "!", "?"}:
            changes.append({**base, "staged": False, "status": _change_label(y)})
    return changes


def git_status(path: str) -> dict[str, object]:
    """Return branch/upstream state and staged/working-tree changes."""
    root = _root(path)
    repository = _capture(root, ["rev-parse", "--is-inside-work-tree"], max_bytes=128)
    if repository.returncode != 0 or repository.output.strip() != "true":
        return {
            "repository": False,
            "branch": None,
            "detached": False,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "clean": True,
            "changes": [],
        }

    branch_result = _capture(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    branch = branch_result.output.strip() if branch_result.returncode == 0 else None
    if branch and (len(branch) > 255 or any(ord(character) < 32 for character in branch)):
        branch = None
    detached = branch is None

    upstream_result = _capture(
        root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
    )
    upstream = upstream_result.output.strip() if upstream_result.returncode == 0 else None
    # A newly connected repository may have tracking config before the first push
    # creates its remote-tracking ref. Surface that intended upstream so the UI can
    # offer the initial publish instead of appearing disconnected.
    if upstream is None and branch:
        configured_remote = _capture(
            root,
            ["config", "--local", "--get", f"branch.{branch}.remote"],
            max_bytes=512,
        )
        configured_merge = _capture(
            root,
            ["config", "--local", "--get", f"branch.{branch}.merge"],
            max_bytes=512,
        )
        remote_name = configured_remote.output.strip()
        merge_ref = configured_merge.output.strip()
        if (
            configured_remote.returncode == 0
            and configured_merge.returncode == 0
            and _REMOTE_RE.fullmatch(remote_name)
            and merge_ref.startswith("refs/heads/")
        ):
            tracked_branch = merge_ref.removeprefix("refs/heads/")
            if tracked_branch and len(tracked_branch) <= 255:
                upstream = f"{remote_name}/{tracked_branch}"
    if upstream and (len(upstream) > 512 or any(ord(character) < 32 for character in upstream)):
        upstream = None

    ahead = 0
    behind = 0
    if upstream:
        counts = _capture(root, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
        if counts.returncode == 0:
            parts = counts.output.strip().split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                ahead, behind = int(parts[0]), int(parts[1])

    porcelain = _capture(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        max_bytes=4_000_000,
    )
    if porcelain.returncode != 0 or porcelain.timed_out or porcelain.truncated:
        _failure(porcelain, "could not read repository status")
    changes = _parse_porcelain(root, porcelain.output)
    return {
        "repository": True,
        "branch": branch,
        "detached": detached,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "clean": not changes,
        "changes": changes,
    }


def git_diff(path: str, rel: str, staged: bool = False) -> dict[str, object]:
    """Return one bounded textual patch without invoking external diff drivers."""
    root = _root(path)
    safe = _safe_status_path(root, rel)
    args = ["diff", "--no-ext-diff", "--no-textconv", "--unified=3"]
    if staged:
        args.append("--cached")
    args.extend(["--", safe])
    result = _capture(root, args, max_bytes=MAX_PATCH_BYTES)
    if result.returncode != 0 or result.timed_out:
        _failure(result, "could not read the diff")
    # A normal Git diff is intentionally empty for an untracked file.  Compare it
    # with the empty device so the review pane can still show its full contents.
    target = root / safe
    if not staged and not result.output and target.is_file():
        untracked = _capture(
            root,
            [
                "diff",
                "--no-index",
                "--no-ext-diff",
                "--no-textconv",
                "--unified=3",
                "--",
                "/dev/null",
                safe,
            ],
            max_bytes=MAX_PATCH_BYTES,
        )
        # --no-index returns 1 when the inputs differ; that is success here.
        if untracked.returncode not in {0, 1} or untracked.timed_out:
            _failure(untracked, "could not read the diff")
        result = untracked
    return {"path": safe, "staged": staged, "patch": result.output, "truncated": result.truncated}


def stage_paths(path: str, paths: list[str]) -> dict[str, object]:
    root = _root(path)
    selected = _validated_paths(root, paths)
    result = _capture(root, ["add", "-A", "--", *selected])
    if result.returncode != 0 or result.timed_out or result.truncated:
        _failure(result, "could not stage the selected paths")
    return git_status(str(root))


def unstage_paths(path: str, paths: list[str]) -> dict[str, object]:
    root = _root(path)
    selected = _validated_paths(root, paths)
    result = _capture(root, ["reset", "--quiet", "HEAD", "--", *selected])
    if result.returncode != 0 or result.timed_out or result.truncated:
        _failure(result, "could not unstage the selected paths")
    return git_status(str(root))


def commit_changes(path: str, message: str) -> dict[str, object]:
    root = _root(path)
    clean_message = message.strip()
    if (
        not clean_message
        or len(clean_message) > MAX_COMMIT_MESSAGE_CHARS
        or "\x00" in clean_message
    ):
        raise SourceControlError("commit message must be between 1 and 5,000 characters")
    current = git_status(str(root))
    if not any(bool(change["staged"]) for change in current["changes"]):
        raise SourceControlError("stage at least one change before committing")

    result = _capture(
        root,
        [
            "-c",
            "user.name=Lemma Local",
            "-c",
            "user.email=noreply@lemma.local",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "--no-verify",
            "--no-gpg-sign",
            "-m",
            clean_message,
        ],
    )
    if result.returncode != 0 or result.timed_out or result.truncated:
        _failure(result, "commit failed")
    commit = _query(root, ["rev-parse", "--short=12", "HEAD"], "could not read commit id")
    summary = _query(root, ["log", "-1", "--pretty=%s"], "could not read commit summary")
    return {"commit": commit, "summary": summary, "status": git_status(str(root))}


def _configured_remote_url(root: Path, remote: str) -> str:
    push = _capture(root, ["config", "--local", "--get-all", f"remote.{remote}.pushurl"])
    values = push.output.splitlines() if push.returncode == 0 else []
    if not values:
        normal = _capture(root, ["config", "--local", "--get-all", f"remote.{remote}.url"])
        values = normal.output.splitlines() if normal.returncode == 0 else []
    values = [value.strip() for value in values if value.strip()]
    if len(values) != 1:
        raise SourceControlError("the selected remote must have exactly one configured push URL")
    url = values[0]
    if len(url) > 2_048 or any(ord(character) < 32 for character in url):
        raise SourceControlError("the configured remote URL is invalid")

    if "://" not in url and _SCP_REMOTE_RE.fullmatch(url):
        return url
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
        raise SourceControlError("only HTTPS and SSH Git remotes can be pushed from the UI")
    if parsed.password is not None or (parsed.scheme == "https" and parsed.username is not None):
        raise SourceControlError("credentials embedded in a remote URL are not accepted")
    return url


def git_remote_info(path: str) -> dict[str, object]:
    """Return repository remotes in a credential-redacted, UI-friendly shape."""
    root = _root(path)
    repository = _capture(root, ["rev-parse", "--is-inside-work-tree"], max_bytes=128)
    if repository.returncode != 0 or repository.output.strip() != "true":
        return {"repository": False, "remotes": []}

    names_result = _capture(root, ["remote"], max_bytes=16_384)
    if names_result.returncode != 0 or names_result.timed_out or names_result.truncated:
        _failure(names_result, "could not read configured remotes")
    names = sorted(
        {
            name.strip()
            for name in names_result.output.splitlines()
            if _REMOTE_RE.fullmatch(name.strip())
        }
    )
    remotes: list[dict[str, object]] = []
    for name in names:
        fetch_result = _capture(
            root,
            ["config", "--local", "--get-all", f"remote.{name}.url"],
            max_bytes=16_384,
        )
        push_result = _capture(
            root,
            ["config", "--local", "--get-all", f"remote.{name}.pushurl"],
            max_bytes=16_384,
        )
        fetch_urls = (
            [value.strip() for value in fetch_result.output.splitlines() if value.strip()]
            if fetch_result.returncode == 0
            else []
        )
        explicit_push_urls = (
            [value.strip() for value in push_result.output.splitlines() if value.strip()]
            if push_result.returncode == 0
            else []
        )
        push_urls = explicit_push_urls or fetch_urls
        fetch = _public_remote_metadata(fetch_urls[0]) if len(fetch_urls) == 1 else None
        push = _public_remote_metadata(push_urls[0]) if len(push_urls) == 1 else None
        protocol = push.get("protocol") if push else None
        provider = push.get("provider") if push else None
        if protocol == "ssh" and provider == "github":
            credential_mode = "ssh"
        elif protocol == "https" and provider == "github":
            credential_mode = (
                "github_cli" if github.GH_EXECUTABLE is not None else "github_cli_required"
            )
        else:
            credential_mode = "unsupported"
        remotes.append(
            {
                "name": name,
                "fetch": fetch,
                "push": push,
                "has_separate_push_url": bool(explicit_push_urls),
                "ambiguous": len(fetch_urls) != 1 or len(push_urls) != 1,
                "push_ready": bool(
                    len(push_urls) == 1
                    and push
                    and push.get("valid")
                    and credential_mode in {"ssh", "github_cli"}
                ),
                "credential_mode": credential_mode,
            }
        )
    status = git_status(str(root))
    return {
        "repository": True,
        "branch": status["branch"],
        "upstream": status["upstream"],
        "remotes": remotes,
    }


def configure_github_remote(
    path: str,
    remote: str,
    url: str,
    *,
    set_upstream: bool = False,
) -> dict[str, object]:
    """Add or update one github.com remote without storing a credential."""
    if not _REMOTE_RE.fullmatch(remote):
        raise SourceControlError("remote name is invalid")
    normalized, _ = _validated_github_remote_url(url.strip())
    root = _root(path)
    repository = _capture(root, ["rev-parse", "--is-inside-work-tree"], max_bytes=128)
    if repository.returncode != 0 or repository.output.strip() != "true":
        raise SourceControlError("workspace is not a Git repository")

    names = _query(root, ["remote"], "could not read configured remotes").splitlines()
    if remote in names:
        update = _capture(
            root,
            ["config", "--local", "--replace-all", f"remote.{remote}.url", normalized],
        )
        if update.returncode != 0 or update.timed_out or update.truncated:
            _failure(update, "could not update the GitHub remote", secret_url=normalized)
        existing_push = _capture(
            root,
            ["config", "--local", "--get-all", f"remote.{remote}.pushurl"],
        )
        if existing_push.returncode == 0 and existing_push.output.strip():
            clear_push = _capture(
                root,
                ["config", "--local", "--unset-all", f"remote.{remote}.pushurl"],
            )
            if clear_push.returncode != 0 or clear_push.timed_out:
                _failure(clear_push, "could not clear the old push URL", secret_url=normalized)
    else:
        add = _capture(root, ["remote", "add", remote, normalized])
        if add.returncode != 0 or add.timed_out or add.truncated:
            _failure(add, "could not add the GitHub remote", secret_url=normalized)

    if set_upstream:
        branch = _query(
            root,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            "check out a branch before setting an upstream",
        )
        checked = _capture(root, ["check-ref-format", "--branch", branch], max_bytes=512)
        if checked.returncode != 0 or checked.timed_out:
            raise SourceControlError("current branch name is invalid")
        for key, value in (
            (f"branch.{branch}.remote", remote),
            (f"branch.{branch}.merge", f"refs/heads/{branch}"),
        ):
            configured = _capture(root, ["config", "--local", key, value])
            if configured.returncode != 0 or configured.timed_out or configured.truncated:
                _failure(configured, "could not configure the branch upstream")
    return git_remote_info(str(root))


def push_branch(
    path: str,
    remote: str,
    branch: str,
    *,
    confirmed: bool,
) -> dict[str, object]:
    """Push current HEAD to its configured upstream without force or arbitrary refs."""
    if not confirmed:
        raise SourceControlError("push requires explicit confirmation")
    if not _REMOTE_RE.fullmatch(remote):
        raise SourceControlError("remote name is invalid")
    root = _root(path)
    current = git_status(str(root))
    if current["detached"] or current["branch"] != branch:
        raise SourceControlError("push branch must match the current checked-out branch")
    upstream = current["upstream"]
    if not isinstance(upstream, str) or not upstream.startswith(f"{remote}/"):
        raise SourceControlError("the selected remote is not the current branch upstream")
    checked = _capture(root, ["check-ref-format", "--branch", branch], max_bytes=512)
    if checked.returncode != 0 or checked.timed_out:
        raise SourceControlError("branch name is invalid")

    remote_url = _configured_remote_url(root, remote)
    credential_args: list[str] = []
    try:
        _, remote_details = _validated_github_remote_url(remote_url)
    except SourceControlError:
        remote_details = {}
    if remote_details.get("protocol") == "https":
        try:
            credential_args = github.https_credential_helper_args()
        except RuntimeError as error:
            raise SourceControlError(
                "GitHub CLI is required for credential-safe HTTPS pushes; "
                "install `gh`, run `gh auth login`, or configure an SSH remote"
            ) from error
    push_environment = {
        "GIT_SSH_COMMAND": (
            "ssh -F /dev/null -oBatchMode=yes -oPermitLocalCommand=no "
            "-oProxyCommand=none -oClearAllForwardings=yes"
        ),
    }
    if remote_details.get("protocol") == "ssh":
        push_environment.update(github.ssh_agent_environment())
    result = git_capture(
        [
            *credential_args,
            "push",
            "--porcelain",
            "--no-verify",
            "--receive-pack=git-receive-pack",
            remote_url,
            f"HEAD:refs/heads/{branch}",
        ],
        root,
        timeout=60,
        max_output_bytes=MAX_PUBLIC_OUTPUT_CHARS,
        extra_env=push_environment,
    )
    if result.returncode != 0 or result.timed_out or result.truncated:
        _failure(result, "push failed", secret_url=remote_url)
    output = _public_output(result.output, remote_url) or f"Pushed {branch} to {remote}."
    return {
        "remote": remote,
        "branch": branch,
        "output": output,
        "status": git_status(str(root)),
    }

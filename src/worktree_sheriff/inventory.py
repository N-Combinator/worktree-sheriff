"""Collect and classify the worktrees of one repository.

Every git invocation here is read-only. ``GIT_OPTIONAL_LOCKS=0`` stops
``git status`` from opportunistically refreshing the index, so a scan leaves
both the working trees and ``.git`` byte-for-byte unchanged.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass

PRUNE_CANDIDATE = "prune-candidate"
RETAIN_DIRTY = "retain-dirty"
RETAIN_UNPUSHED = "retain-unpushed"
INSPECT = "inspect"

PRUNE_COMMAND = "git worktree prune --dry-run"

NULL_SHA = "0" * 40

# Variables that would make git ignore ``-C <path>`` when locating a repository
# (for example when the tool is run from inside a git hook).
_REPO_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)


class GitNotFoundError(Exception):
    """The git executable could not be started."""


class NotARepositoryError(Exception):
    """The given path is not inside a git repository."""

    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


class GitError(Exception):
    """A git command failed unexpectedly."""


@dataclass
class Worktree:
    path: str
    head: str | None
    branch: str | None
    class_: str
    reason: str
    suggested_command: str | None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "head": self.head,
            "branch": self.branch,
            "class": self.class_,
            "reason": self.reason,
            "suggested_command": self.suggested_command,
        }


@dataclass
class _Entry:
    path: str
    head: str | None = None
    branch: str | None = None
    bare: bool = False
    detached: bool = False
    locked: str | None = None


def _git_env() -> dict:
    env = {key: value for key, value in os.environ.items() if key not in _REPO_ENV_VARS}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["LC_ALL"] = "C"
    return env


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=_git_env(),
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitNotFoundError("git executable not found on PATH") from exc


def _checked(proc: subprocess.CompletedProcess, what: str) -> str:
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip().splitlines()
        raise GitError(f"{what} failed: {detail[-1] if detail else 'exit code ' + str(proc.returncode)}")
    return proc.stdout.decode(errors="surrogateescape")


def parse_porcelain(output: str, nul: bool) -> list[_Entry]:
    """Parse ``git worktree list --porcelain`` output (with or without ``-z``)."""
    sep = "\0" if nul else "\n"
    entries: list[_Entry] = []
    current: _Entry | None = None
    for line in output.split(sep):
        if not line:
            current = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = _Entry(path=value)
            entries.append(current)
        elif current is None:
            continue
        elif key == "HEAD":
            current.head = None if value == NULL_SHA else value
        elif key == "branch":
            current.branch = value.removeprefix("refs/heads/")
        elif key == "bare":
            current.bare = True
        elif key == "detached":
            current.detached = True
        elif key == "locked":
            current.locked = value
    return entries


def _list_worktrees(path: str) -> list[_Entry]:
    proc = _run_git(["worktree", "list", "--porcelain", "-z"], path)
    if proc.returncode == 0:
        return parse_porcelain(proc.stdout.decode(errors="surrogateescape"), nul=True)
    # git older than 2.36 has no -z for worktree list.
    out = _checked(_run_git(["worktree", "list", "--porcelain"], path), "git worktree list")
    return parse_porcelain(out, nul=False)


def _is_worktree_root(path: str) -> bool:
    """True when git sees ``path`` itself as the top of a working tree.

    Guards against a directory that still exists but lost its ``.git`` file:
    git would then silently fall through to an enclosing repository.
    """
    proc = _run_git(["rev-parse", "--show-toplevel"], path)
    if proc.returncode != 0:
        return False
    top = proc.stdout.decode(errors="surrogateescape").strip()
    return os.path.realpath(top) == os.path.realpath(path)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _classify(entry: _Entry, repo: str) -> tuple[str, str]:
    if not os.path.exists(entry.path):
        return PRUNE_CANDIDATE, "path does not exist on disk"

    if entry.bare:
        return INSPECT, "bare repository, no working tree"

    if not _is_worktree_root(entry.path):
        return INSPECT, "path exists but git does not recognise it as this working tree"

    status = _checked(
        _run_git(["status", "--porcelain", "--untracked-files=normal"], entry.path),
        f"git status in {entry.path}",
    )
    lines = [line for line in status.splitlines() if line]
    if lines:
        untracked = sum(1 for line in lines if line.startswith("??"))
        changed = len(lines) - untracked
        parts = []
        if changed:
            parts.append(_plural(changed, "uncommitted change"))
        if untracked:
            parts.append(_plural(untracked, "untracked path"))
        return RETAIN_DIRTY, ", ".join(parts)

    if entry.head is None:
        return INSPECT, "no commits yet"

    count = int(
        _checked(
            _run_git(["rev-list", "--count", entry.head, "--not", "--remotes"], repo),
            f"git rev-list for {entry.path}",
        ).strip()
    )
    if count:
        return RETAIN_UNPUSHED, f"{_plural(count, 'commit')} not on any remote"

    if entry.detached:
        return INSPECT, f"detached HEAD at {entry.head[:12]}, clean, all commits on a remote"
    return INSPECT, f"clean, all commits of branch {entry.branch} on a remote"


def _suggested_command(class_: str, path: str) -> str | None:
    if class_ == PRUNE_CANDIDATE:
        return PRUNE_COMMAND
    if class_ == INSPECT:
        return f"git -C {shlex.quote(path)} status"
    return None


def scan(path: str) -> list[Worktree]:
    """Return every registered worktree of the repository containing ``path``, sorted by path."""
    if _run_git(["rev-parse", "--git-dir"], path).returncode != 0:
        raise NotARepositoryError(path)

    worktrees = []
    for entry in _list_worktrees(path):
        class_, reason = _classify(entry, path)
        if entry.locked is not None:
            reason += f"; locked ({entry.locked})" if entry.locked else "; locked"
        worktrees.append(
            Worktree(
                path=entry.path,
                head=entry.head,
                branch=None if entry.detached else entry.branch,
                class_=class_,
                reason=reason,
                suggested_command=_suggested_command(class_, entry.path),
            )
        )
    return sorted(worktrees, key=lambda w: w.path)

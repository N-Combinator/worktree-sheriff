from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from conftest import commit, git
from worktree_sheriff import cli


def tree_hash(root: Path) -> str:
    """Hash names, types, modes, mtimes and contents of everything under root, including .git."""
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in [dirpath, *(os.path.join(dirpath, f) for f in sorted(filenames))]:
            st = os.lstat(name)
            digest.update(os.path.relpath(name, root).encode())
            digest.update(f"{st.st_mode}:{st.st_size}:{st.st_mtime_ns}".encode())
            if os.path.islink(name):
                digest.update(os.readlink(name).encode())
            elif os.path.isfile(name):
                digest.update(Path(name).read_bytes())
    return digest.hexdigest()


def snapshot(repo: Path, root: Path) -> tuple[str, str]:
    return git(repo, "worktree", "list", "--porcelain"), tree_hash(root)


def test_scan_changes_nothing(repo: Path, root: Path, capsys):
    def add(name: str, *extra: str) -> Path:
        path = root / name
        git(repo, "worktree", "add", "-q", *extra, str(path), "origin/main")
        return path

    add("clean", "-b", "clean")
    (add("dirty", "-b", "dirty") / "README").write_text("changed\n")
    (add("untracked", "-b", "untracked") / "new.txt").write_text("new\n")
    tracked = add("tracked", "-b", "tracked")
    commit(tracked, "a.txt")
    git(tracked, "push", "-q", "-u", "origin", "tracked")
    commit(tracked, "b.txt")
    commit(add("local", "-b", "local"), "c.txt")
    add("detached", "--detach")
    shutil.rmtree(add("gone", "-b", "gone"))
    # Make the index stat data stale so a writing `git status` would refresh it.
    os.utime(root / "clean" / "README", ns=(1, 1))

    before = snapshot(repo, root)
    classes = set()
    for target in (repo, root / "clean", root / "dirty"):
        for fmt in ("json", "markdown"):
            assert cli.main(["scan", str(target), "--format", fmt]) == 0
        out = capsys.readouterr().out
        classes.update(c for c in ("prune-candidate", "retain-dirty", "retain-unpushed", "inspect") if c in out)
    after = snapshot(repo, root)

    assert classes == {"prune-candidate", "retain-dirty", "retain-unpushed", "inspect"}
    assert after[0] == before[0]
    assert after[1] == before[1]

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from conftest import commit, git
from worktree_sheriff import inventory
from worktree_sheriff.inventory import scan


def by_path(repo: Path) -> dict:
    return {w.path: w for w in scan(str(repo))}


def test_clean_pushed_branch_is_inspect(repo: Path, root: Path):
    wt = root / "clean"
    git(repo, "worktree", "add", "-q", "-b", "clean", str(wt), "origin/main")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "inspect"
    assert result.branch == "clean"
    assert result.head == git(wt, "rev-parse", "HEAD").strip()
    assert "clean" in result.reason
    assert result.suggested_command == f"git -C {wt} status"


def test_main_checkout_is_listed_and_classified(repo: Path):
    result = by_path(repo)[str(repo)]

    assert result.class_ == "inspect"
    assert result.branch == "main"


def test_modified_tracked_file_is_retain_dirty(repo: Path, root: Path):
    wt = root / "dirty"
    git(repo, "worktree", "add", "-q", "-b", "dirty", str(wt), "origin/main")
    (wt / "README").write_text("changed\n")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "retain-dirty"
    assert result.reason == "1 uncommitted change"
    assert result.suggested_command is None


def test_untracked_only_is_retain_dirty(repo: Path, root: Path):
    wt = root / "untracked"
    git(repo, "worktree", "add", "-q", "-b", "untracked", str(wt), "origin/main")
    (wt / "new-a.txt").write_text("a\n")
    (wt / "new-b.txt").write_text("b\n")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "retain-dirty"
    assert result.reason == "2 untracked paths"
    assert result.suggested_command is None


def test_untracked_detected_even_when_config_hides_untracked_files(repo: Path, root: Path):
    wt = root / "hidden"
    git(repo, "worktree", "add", "-q", "-b", "hidden", str(wt), "origin/main")
    git(repo, "config", "status.showUntrackedFiles", "no")
    (wt / "new.txt").write_text("a\n")

    assert by_path(repo)[str(wt)].class_ == "retain-dirty"


def test_dirty_wins_over_unpushed(repo: Path, root: Path):
    wt = root / "both"
    git(repo, "worktree", "add", "-q", "-b", "both", str(wt), "origin/main")
    commit(wt, "local.txt")
    (wt / "scratch.txt").write_text("s\n")
    (wt / "README").write_text("changed\n")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "retain-dirty"
    assert result.reason == "1 uncommitted change, 1 untracked path"


def test_unpushed_commits_on_tracking_branch(repo: Path, root: Path):
    wt = root / "tracked"
    git(repo, "worktree", "add", "-q", "-b", "tracked", str(wt), "origin/main")
    commit(wt, "one.txt")
    git(wt, "push", "-q", "-u", "origin", "tracked")
    commit(wt, "two.txt")
    commit(wt, "three.txt")

    result = by_path(repo)[str(wt)]

    assert git(wt, "rev-parse", "--abbrev-ref", "@{upstream}").strip() == "origin/tracked"
    assert result.class_ == "retain-unpushed"
    assert result.reason == "2 commits not on any remote"
    assert result.suggested_command is None


def test_branch_without_upstream_is_retain_unpushed(repo: Path, root: Path):
    wt = root / "local"
    git(repo, "worktree", "add", "-q", "-b", "local", str(wt), "origin/main")
    commit(wt, "a.txt")
    commit(wt, "b.txt")
    commit(wt, "c.txt")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "retain-unpushed"
    assert result.reason == "3 commits not on any remote"


def test_commit_on_another_remote_branch_counts_as_pushed(repo: Path, root: Path):
    wt = root / "elsewhere"
    git(repo, "worktree", "add", "-q", "-b", "elsewhere", str(wt), "origin/main")
    commit(wt, "a.txt")
    git(wt, "push", "-q", "origin", "HEAD:refs/heads/other-name")

    assert by_path(repo)[str(wt)].class_ == "inspect"


def test_detached_head_is_inspect(repo: Path, root: Path):
    wt = root / "detached"
    git(repo, "worktree", "add", "-q", "--detach", str(wt), "origin/main")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "inspect"
    assert result.branch is None
    assert "detached HEAD" in result.reason
    assert result.suggested_command == f"git -C {wt} status"


def test_detached_head_with_unpushed_commit_is_retain_unpushed(repo: Path, root: Path):
    wt = root / "detached-work"
    git(repo, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    commit(wt, "a.txt")

    result = by_path(repo)[str(wt)]

    assert result.class_ == "retain-unpushed"
    assert result.branch is None


def test_missing_path_is_prune_candidate(repo: Path, root: Path):
    wt = root / "gone"
    git(repo, "worktree", "add", "-q", "-b", "gone", str(wt), "origin/main")
    commit(wt, "unpushed.txt")
    shutil.rmtree(wt)

    result = by_path(repo)[str(wt)]

    assert result.class_ == "prune-candidate"
    assert result.reason == "path does not exist on disk"
    assert result.suggested_command == "git worktree prune --dry-run"


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_parent_is_inspect_not_prune_candidate(repo: Path, root: Path):
    parent = root / "locked-away"
    wt = parent / "wt"
    git(repo, "worktree", "add", "-q", "-b", "hidden-away", str(wt), "origin/main")
    other = root / "other"
    git(repo, "worktree", "add", "-q", "-b", "other", str(other), "origin/main")
    commit(other, "a.txt")
    parent.chmod(0)
    try:
        results = by_path(repo)
    finally:
        parent.chmod(0o755)

    assert results[str(wt)].class_ == "inspect"
    assert results[str(wt)].reason == "cannot stat: EACCES"
    assert results[str(wt)].suggested_command == f"git -C {wt} status"
    assert results[str(other)].class_ == "retain-unpushed"


def test_stale_file_handle_is_inspect_not_prune_candidate(repo: Path, root: Path, monkeypatch):
    wt = root / "nfs"
    git(repo, "worktree", "add", "-q", "-b", "nfs", str(wt), "origin/main")
    real_stat = os.stat

    def stale_stat(path, *args, **kwargs):
        if os.fspath(path) == str(wt):
            raise OSError(errno.ESTALE, os.strerror(errno.ESTALE), str(wt))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(inventory.os, "stat", stale_stat)
    result = by_path(repo)[str(wt)]

    assert result.class_ == "inspect"
    assert result.reason == "cannot stat: ESTALE"


def test_git_status_failure_marks_only_that_worktree_inspect(repo: Path, root: Path):
    broken = root / "corrupt-index"
    git(repo, "worktree", "add", "-q", "-b", "corrupt-index", str(broken), "origin/main")
    dirty = root / "dirty"
    git(repo, "worktree", "add", "-q", "-b", "dirty", str(dirty), "origin/main")
    (dirty / "README").write_text("changed\n")
    (repo / ".git" / "worktrees" / "corrupt-index" / "index").write_text("garbage\n")

    results = by_path(repo)

    assert results[str(broken)].class_ == "inspect"
    assert results[str(broken)].reason.startswith("git status failed: ")
    assert "index file" in results[str(broken)].reason
    assert results[str(broken)].suggested_command == f"git -C {broken} status"
    assert results[str(dirty)].class_ == "retain-dirty"
    assert results[str(repo)].class_ == "inspect"


def test_git_rev_list_failure_marks_only_that_worktree_inspect(repo: Path, root: Path):
    broken = root / "missing-object"
    git(repo, "worktree", "add", "-q", "-b", "missing-object", str(broken), "origin/main")
    commit(broken, "a.txt")
    parent = git(broken, "rev-parse", "HEAD").strip()
    commit(broken, "b.txt")
    unpushed = root / "unpushed"
    git(repo, "worktree", "add", "-q", "-b", "unpushed", str(unpushed), "origin/main")
    commit(unpushed, "c.txt")
    # Status only needs HEAD and its tree; the history walk needs the missing parent.
    (repo / ".git" / "objects" / parent[:2] / parent[2:]).unlink()

    results = by_path(repo)

    assert results[str(broken)].class_ == "inspect"
    assert results[str(broken)].reason.startswith("git rev-list failed: ")
    assert results[str(unpushed)].class_ == "retain-unpushed"
    assert results[str(unpushed)].reason == "1 commit not on any remote"


def test_locked_worktree_mentions_lock(repo: Path, root: Path):
    wt = root / "locked"
    git(repo, "worktree", "add", "-q", "-b", "locked", str(wt), "origin/main")
    git(repo, "worktree", "lock", "--reason", "usb disk", str(wt))
    shutil.rmtree(wt)

    result = by_path(repo)[str(wt)]

    assert result.class_ == "prune-candidate"
    assert result.reason == "path does not exist on disk; locked (usb disk)"


def test_path_that_lost_its_git_file_does_not_fall_through_to_parent_repo(repo: Path):
    wt = repo / "nested"
    git(repo, "worktree", "add", "-q", "-b", "nested", str(wt), "origin/main")
    (wt / ".git").unlink()

    result = by_path(repo)[str(wt)]

    assert result.class_ == "inspect"
    assert "not recognise" in result.reason


def test_scan_from_linked_worktree_matches_scan_from_main(repo: Path, root: Path):
    wt = root / "linked"
    git(repo, "worktree", "add", "-q", "-b", "linked", str(wt), "origin/main")
    commit(wt, "a.txt")
    (wt / "sub").mkdir()

    from_main = [w.to_dict() for w in scan(str(repo))]
    from_linked = [w.to_dict() for w in scan(str(wt / "sub"))]

    assert from_main == from_linked


def test_results_sorted_by_path(repo: Path, root: Path):
    for name in ("zeta", "alpha", "mid"):
        git(repo, "worktree", "add", "-q", "-b", name, str(root / name), "origin/main")

    paths = [w.path for w in scan(str(repo))]

    assert paths == sorted(paths)
    assert len(paths) == 4


def test_repository_without_commits(root: Path):
    empty = root / "empty"
    git(root, "init", "-q", str(empty))

    [result] = scan(str(empty))

    assert result.head is None
    assert result.class_ == "inspect"
    assert result.reason == "no commits yet"


def test_bare_repository_entry(root: Path, repo: Path):
    bare = root / "remote.git"
    wt = root / "from-bare"
    git(bare, "worktree", "add", "-q", str(wt), "main")

    results = by_path(bare)

    assert results[str(bare)].class_ == "inspect"
    assert results[str(bare)].reason == "bare repository, no working tree"
    # The bare repository has no remotes of its own, so its commits are unpushed from its point of view.
    assert results[str(wt)].class_ == "retain-unpushed"

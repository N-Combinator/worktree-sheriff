from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return proc.stdout


def commit(worktree: Path, name: str, content: str = "x\n") -> None:
    (worktree / name).write_text(content)
    git(worktree, "add", name)
    git(worktree, "commit", "-q", "-m", f"add {name}")


@pytest.fixture(autouse=True)
def isolated_git(tmp_path_factory, monkeypatch):
    """Keep the developer's git config and any surrounding repository out of the tests."""
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text("[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(Path(tmp_path_factory.getbasetemp()).resolve()))
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path.resolve()


@pytest.fixture
def repo(root: Path) -> Path:
    """A main checkout with one pushed commit on `main` and a bare repository as `origin`."""
    remote = root / "remote.git"
    main = root / "main"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    git(main, "checkout", "-q", "-b", "main")
    commit(main, "README")
    git(main, "remote", "add", "origin", str(remote))
    git(main, "push", "-q", "-u", "origin", "main")
    return main

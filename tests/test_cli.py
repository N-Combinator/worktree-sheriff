from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import commit, git
from worktree_sheriff import cli, inventory
from worktree_sheriff.render import COLUMNS

SRC = Path(__file__).resolve().parent.parent / "src"


def run_cli(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_json_output_shape(repo: Path, root: Path, capsys):
    git(repo, "worktree", "add", "-q", "-b", "feature", str(root / "feature"), "origin/main")
    git(repo, "worktree", "add", "-q", "--detach", str(root / "bisect"), "origin/main")
    commit(root / "feature", "a.txt")

    code, out, err = run_cli(capsys, "scan", str(repo), "--format", "json")

    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert [list(item) for item in data] == [list(COLUMNS)] * 3
    assert [item["path"] for item in data] == sorted(item["path"] for item in data)
    by_path = {item["path"]: item for item in data}
    assert by_path[str(root / "bisect")]["branch"] is None
    assert by_path[str(root / "feature")] == {
        "path": str(root / "feature"),
        "head": git(root / "feature", "rev-parse", "HEAD").strip(),
        "branch": "feature",
        "class": "retain-unpushed",
        "reason": "1 commit not on any remote",
        "suggested_command": None,
    }


def test_json_is_the_default_format(repo: Path, capsys):
    _, default_out, _ = run_cli(capsys, "scan", str(repo))
    _, json_out, _ = run_cli(capsys, "scan", str(repo), "--format", "json")

    assert default_out == json_out


def test_markdown_output(repo: Path, root: Path, capsys):
    git(repo, "worktree", "add", "-q", "--detach", str(root / "bisect"), "origin/main")

    code, out, _ = run_cli(capsys, "scan", str(repo), "--format", "markdown")

    head = git(repo, "rev-parse", "HEAD").strip()
    assert code == 0
    assert out.splitlines() == [
        "| path | head | branch | class | reason | suggested_command |",
        "|---|---|---|---|---|---|",
        f"| {root / 'bisect'} | {head} |  | inspect | detached HEAD at {head[:12]}, clean, all commits on a remote"
        f" | git -C {root / 'bisect'} status |",
        f"| {repo} | {head} | main | inspect | clean, all commits of branch main on a remote | git -C {repo} status |",
    ]


def test_markdown_escapes_pipes(repo: Path, root: Path, capsys):
    wt = root / "a|b"
    git(repo, "worktree", "add", "-q", "-b", "pipe", str(wt), "origin/main")

    _, out, _ = run_cli(capsys, "scan", str(repo), "--format", "markdown")

    row = next(line for line in out.splitlines() if "pipe" in line)
    assert "a\\|b" in row
    assert row.replace("\\|", "").count("|") == len(COLUMNS) + 1


def test_suggested_command_quotes_paths_with_spaces(repo: Path, root: Path, capsys):
    wt = root / "with space"
    git(repo, "worktree", "add", "-q", "-b", "space", str(wt), "origin/main")

    _, out, _ = run_cli(capsys, "scan", str(repo))

    item = next(item for item in json.loads(out) if item["branch"] == "space")
    assert item["suggested_command"] == f"git -C '{wt}' status"


def test_not_a_repository_exits_2_naming_the_path(root: Path, capsys):
    plain = root / "plain"
    plain.mkdir()

    code, out, err = run_cli(capsys, "scan", str(plain))

    assert code == 2
    assert out == ""
    assert err.count("\n") == 1
    assert str(plain) in err


def test_nonexistent_path_exits_2(root: Path, capsys):
    code, out, err = run_cli(capsys, "scan", str(root / "nope"))

    assert code == 2
    assert out == ""
    assert str(root / "nope") in err


def test_git_not_on_path_exits_2(repo: Path, root: Path, monkeypatch, capsys):
    empty = root / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    code, out, err = run_cli(capsys, "scan", str(repo))

    assert code == 2
    assert out == ""
    assert "git" in err
    assert err.count("\n") == 1


def test_unknown_format_is_a_usage_error(repo: Path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["scan", str(repo), "--format", "yaml"])
    assert exc.value.code == 2


def test_cli_offers_no_mutating_commands_or_flags():
    parser = cli.build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")

    assert set(subparsers.choices) == {"scan"}
    scan_options = {a.dest for a in subparsers.choices["scan"]._actions}
    assert scan_options == {"help", "path", "format"}


def test_scan_only_runs_read_only_git_commands(repo: Path, root: Path, monkeypatch):
    git(repo, "worktree", "add", "-q", "-b", "feature", str(root / "feature"), "origin/main")
    git(repo, "worktree", "add", "-q", "-b", "gone", str(root / "gone"), "origin/main")
    shutil.rmtree(root / "gone")
    calls = []
    real_run = subprocess.run

    def recording_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(inventory.subprocess, "run", recording_run)
    inventory.scan(str(repo))

    allowed = {("rev-parse",), ("worktree", "list"), ("status",), ("rev-list",)}
    for cmd in calls:
        assert cmd[:2] == ["git", "-C"]
        sub = tuple(cmd[3:5]) if cmd[3] == "worktree" else (cmd[3],)
        assert sub in allowed, cmd
    assert any(cmd[3] == "status" for cmd in calls)


def test_module_entry_point(repo: Path):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(
        [sys.executable, "-m", "worktree_sheriff", "scan", str(repo), "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)[0]["path"] == str(repo)

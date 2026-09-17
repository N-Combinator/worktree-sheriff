"""Output formats for a scan."""

from __future__ import annotations

import json

from worktree_sheriff.inventory import Worktree

COLUMNS = ("path", "head", "branch", "class", "reason", "suggested_command")


def to_json(worktrees: list[Worktree]) -> str:
    return json.dumps([w.to_dict() for w in worktrees], indent=2)


def _cell(value: str | None) -> str:
    if value is None:
        return ""
    return value.replace("|", "\\|").replace("\n", " ")


def to_markdown(worktrees: list[Worktree]) -> str:
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join("---" for _ in COLUMNS) + "|",
    ]
    for worktree in worktrees:
        row = worktree.to_dict()
        lines.append("| " + " | ".join(_cell(row[column]) for column in COLUMNS) + " |")
    return "\n".join(lines)

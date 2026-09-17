"""Command-line interface.

There is deliberately only one subcommand, ``scan``, and it never writes.
"""

from __future__ import annotations

import argparse
import sys

from worktree_sheriff import __version__
from worktree_sheriff.inventory import GitError, GitNotFoundError, NotARepositoryError, scan
from worktree_sheriff.render import to_json, to_markdown

EXIT_OK = 0
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worktree-sheriff",
        description="Read-only safety inventory of a repository's git worktrees.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="command")
    scan_parser = subcommands.add_parser(
        "scan",
        help="classify every worktree of the repository containing PATH",
        description="Classify every registered worktree of the repository containing PATH. Nothing is modified.",
    )
    scan_parser.add_argument("path", help="main checkout or any linked worktree of the repository")
    scan_parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="output format (default: json)",
    )
    return parser


def _error(message: str) -> int:
    print(f"worktree-sheriff: {message}", file=sys.stderr)
    return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        worktrees = scan(args.path)
    except GitNotFoundError:
        return _error("git executable not found on PATH")
    except NotARepositoryError as exc:
        return _error(f"not inside a git repository: {exc.path}")
    except GitError as exc:
        return _error(str(exc))

    output = to_json(worktrees) if args.format == "json" else to_markdown(worktrees)
    if hasattr(sys.stdout, "reconfigure"):
        # Undecodable path bytes are carried as surrogates; print them escaped.
        sys.stdout.reconfigure(errors="backslashreplace")
    print(output)
    return EXIT_OK

# worktree-sheriff

Read-only Git worktree safety inventory for busy repositories.

`worktree-sheriff scan` lists every worktree registered in a repository and tells you, for each one,
whether it is safe to forget about or still holds work: uncommitted edits, untracked files or commits
that exist on no remote. It never deletes, prunes or modifies anything — there is no command or flag
that could. Python ≥ 3.10, standard library only, needs `git` on `PATH`.

## Install

From a checkout:

```sh
pip install .
```

From a GitHub Release wheel (replace the version with the release you want):

```sh
pip install https://github.com/N-Combinator/worktree-sheriff/releases/download/v0.1.0/worktree_sheriff-0.1.0-py3-none-any.whl
```

## Usage

```
worktree-sheriff scan <path> [--format json|markdown]
```

`<path>` can be the main checkout, any linked worktree, or any directory inside one of them; the result
is the same. Output is sorted by path. `--format` defaults to `json`.

### JSON

```console
$ worktree-sheriff scan /work/app --format json
[
  {
    "path": "/work/app",
    "head": "23df8a8098e95fb30ef129320e378141ab2bee00",
    "branch": "main",
    "class": "inspect",
    "reason": "clean, all commits of branch main on a remote",
    "suggested_command": "git -C /work/app status"
  },
  {
    "path": "/work/app-bisect",
    "head": "23df8a8098e95fb30ef129320e378141ab2bee00",
    "branch": null,
    "class": "inspect",
    "reason": "detached HEAD at 23df8a8098e9, clean, all commits on a remote",
    "suggested_command": "git -C /work/app-bisect status"
  },
  {
    "path": "/work/app-fix-login",
    "head": "23df8a8098e95fb30ef129320e378141ab2bee00",
    "branch": "fix-login",
    "class": "retain-dirty",
    "reason": "1 uncommitted change",
    "suggested_command": null
  },
  {
    "path": "/work/app-old",
    "head": "23df8a8098e95fb30ef129320e378141ab2bee00",
    "branch": "old",
    "class": "prune-candidate",
    "reason": "path does not exist on disk",
    "suggested_command": "git worktree prune --dry-run"
  },
  {
    "path": "/work/app-spike",
    "head": "b75f6ff01923bd5556bca38d483f8b6a5027ddd0",
    "branch": "spike",
    "class": "retain-unpushed",
    "reason": "3 commits not on any remote",
    "suggested_command": null
  }
]
```

`branch` is `null` for a detached HEAD; `head` is `null` for a branch with no commits yet.

### Markdown

```console
$ worktree-sheriff scan /work/app-spike --format markdown
| path | head | branch | class | reason | suggested_command |
|---|---|---|---|---|---|
| /work/app | 23df8a8098e95fb30ef129320e378141ab2bee00 | main | inspect | clean, all commits of branch main on a remote | git -C /work/app status |
| /work/app-bisect | 23df8a8098e95fb30ef129320e378141ab2bee00 |  | inspect | detached HEAD at 23df8a8098e9, clean, all commits on a remote | git -C /work/app-bisect status |
| /work/app-fix-login | 23df8a8098e95fb30ef129320e378141ab2bee00 | fix-login | retain-dirty | 1 uncommitted change |  |
| /work/app-old | 23df8a8098e95fb30ef129320e378141ab2bee00 | old | prune-candidate | path does not exist on disk | git worktree prune --dry-run |
| /work/app-spike | b75f6ff01923bd5556bca38d483f8b6a5027ddd0 | spike | retain-unpushed | 3 commits not on any remote |  |
```

Columns are always `path | head | branch | class | reason | suggested_command`; `null` values are empty
cells and `|` inside a value is escaped as `\|`.

## Classes

Each worktree gets the first class whose condition matches:

| class | condition | suggested_command |
|---|---|---|
| `prune-candidate` | the worktree path does not exist on disk (`stat` fails with `ENOENT`) | `git worktree prune --dry-run` |
| `retain-dirty` | uncommitted or untracked changes (`git status --porcelain` is non-empty) | `null` |
| `retain-unpushed` | commits reachable from HEAD but not from any `refs/remotes/*` ref (includes branches with no upstream) | `null` |
| `inspect` | detached HEAD or anything else (clean and fully pushed, bare, no commits yet, path cannot be checked) | `git -C <path> status` |

`reason` states the evidence, e.g. `3 commits not on any remote` or `1 uncommitted change, 2 untracked
paths`. Locked worktrees get `; locked (<reason>)` appended. Untracked files are counted even if
`status.showUntrackedFiles` is `no`; ignored files are not.

A worktree that cannot be checked is `inspect`, never `prune-candidate`: if `stat` fails with anything other
than `ENOENT` (permission denied, stale NFS handle, ...) the reason is `cannot stat: <errno>`, e.g.
`cannot stat: EACCES`; if `git status` or `git rev-list` fails in one worktree (corrupt index, missing
objects, ...) the reason is git's error, e.g. `git status failed: fatal: ... index file smaller than
expected`. The other worktrees are classified as usual and the exit code stays 0.

"Not on any remote" is judged against the remote-tracking refs you already have locally — the scan does
not fetch. Run `git fetch --all` first if they may be stale.

## Exit codes

| code | meaning |
|---|---|
| 0 | scan completed (whatever the classes) |
| 2 | `<path>` is not inside a git repository, `git` is not on `PATH`, `git worktree list` failed, or invalid arguments |

Errors are a single line on stderr naming the problem, e.g.
`worktree-sheriff: not inside a git repository: /tmp/notes`.

## Read-only guarantee

The scan only runs `git rev-parse`, `git worktree list --porcelain`, `git status --porcelain` and
`git rev-list --count`, all with `GIT_OPTIONAL_LOCKS=0` so `git status` does not refresh the index. The
test suite hashes the whole temporary repository tree (including `.git`) and `git worktree list
--porcelain` before and after a scan and requires them to be identical.

## Similar tools

- **bonsai** — a Go tool that manages agent worktrees across the whole machine, with a plan/apply flow that
  removes them.
- **`git worktree prune`** — built into git; removes administrative data for worktrees whose directory is
  gone, and says nothing about worktrees that still exist.

How worktree-sheriff differs:

- installs with pip and runs on the Python standard library alone;
- scoped to one repository, and covers every worktree registered there, however it was created;
- classifies existing worktrees, including dirty and untracked-only ones, not just missing paths;
- has no removal path at all — it only reports, and at most suggests `git worktree prune --dry-run`;
- stable JSON output and exit codes (0 on a completed scan, 2 on errors) for use in CI and scripts.

## Development

```sh
pip install -e ".[dev]"
pytest -q
```

Releases: bump `version` in `pyproject.toml` and `src/worktree_sheriff/__init__.py`, then push a matching
`v<version>` tag. The release workflow runs the tests, checks the tag against `pyproject.toml`, and attaches the
sdist and wheel to a GitHub Release.

## License

MIT

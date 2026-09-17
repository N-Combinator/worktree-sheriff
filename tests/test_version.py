import re
from pathlib import Path

from worktree_sheriff import __version__


def test_package_version_matches_pyproject():
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)

    assert match and match.group(1) == __version__

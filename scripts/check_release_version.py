"""Fails when a release tag and the app's version disagree. The in-app update check compares the latest release tag with
the version baked into the app from pyproject.toml, so a tag that does not match would make every install say
"update available" (or never say it).

    python scripts/check_release_version.py v1.9.2
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def project_version(pyproject: Path) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit("no version found in pyproject.toml")
    return match.group(1)


def check(tag: str, version: str) -> str | None:
    """None when the tag is v<version> (or <version>); otherwise the problem."""
    if tag.strip().lstrip("v") != version:
        return f"release tag '{tag}' does not match pyproject.toml version '{version}'. Bump the version first, or fix the tag."
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    problem = check(argv[1], project_version(Path(__file__).resolve().parents[1] / "pyproject.toml"))
    print(problem or f"ok: {argv[1]} matches pyproject.toml")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

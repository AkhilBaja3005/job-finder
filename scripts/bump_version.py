"""Bumps the app version in every place it lives and writes the changelog entry from the merged PR titles since the last tag.

    python scripts/bump_version.py patch            # 1.9.3 -> 1.9.4
    python scripts/bump_version.py minor|major
    python scripts/bump_version.py 2.0.0            # an exact version
    python scripts/bump_version.py patch --dry-run  # show the new version and the changelog entry, change nothing

PR titles follow `feat(area): ...` / `fix(area): ...`; feat goes under Added, fix under Fixed, anything else without a
ci/test/docs/chore/release prefix under Changed. Merge commits and housekeeping prefixes are left out.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = [
    (ROOT / "pyproject.toml", re.compile(r'^(version\s*=\s*")([^"]+)(")', re.M)),
    (ROOT / "backend" / "config" / "constants.py", re.compile(r'^(APP_VERSION\s*=\s*")([^"]+)(")', re.M)),
    (ROOT / "job_finder" / "__init__.py", re.compile(r'^(__version__\s*=\s*")([^"]+)(")', re.M)),
    (ROOT / "backend" / "job_finder_mcp" / "__init__.py", re.compile(r'^(__version__\s*=\s*")([^"]+)(")', re.M)),
]
SKIP_PREFIXES = {"ci", "test", "tests", "docs", "chore", "release", "build"}
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?!?:\s*(?P<text>.+?)(?:\s*\(#(?P<pr>\d+)\))?$")


def current_version() -> str:
    match = VERSION_FILES[0][1].search(VERSION_FILES[0][0].read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("no version in pyproject.toml")
    return match.group(2)


def next_version(current: str, spec: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", spec):
        return spec
    parts = [int(p) for p in current.split(".")]
    if spec == "patch":
        parts[2] += 1
    elif spec == "minor":
        parts[1], parts[2] = parts[1] + 1, 0
    elif spec == "major":
        parts[0], parts[1], parts[2] = parts[0] + 1, 0, 0
    else:
        raise SystemExit(f"'{spec}' is not patch, minor, major or a version like 1.2.3")
    return ".".join(str(p) for p in parts)


def classify(subject: str) -> Optional[tuple]:
    """(section, text) for a commit subject, or None when it should not appear in the changelog."""
    subject = subject.strip()
    if not subject or subject.lower().startswith(("merge ", "revert ")):
        return None
    m = SUBJECT.match(subject)
    if m:
        kind = m.group("type")
        if kind in SKIP_PREFIXES:
            return None
        text = m.group("text").strip()
        return ("Added" if kind == "feat" else "Fixed" if kind == "fix" else "Changed", text[:1].upper() + text[1:])
    text = re.sub(r"\s*\(#\d+\)$", "", subject)
    return ("Changed", text[:1].upper() + text[1:])


def changelog_entry(version: str, subjects: List[str]) -> str:
    sections: dict = {"Added": [], "Fixed": [], "Changed": []}
    for subject in subjects:
        item = classify(subject)
        if item and item[1] not in sections[item[0]]:
            sections[item[0]].append(item[1])
    lines = [f"## {version}", ""]
    for name, items in sections.items():
        if items:
            lines += [f"### {name}"] + [f"- {t}" for t in items] + [""]
    if len(lines) == 2:
        lines += ["- Maintenance release.", ""]
    return "\n".join(lines) + "\n"


def last_tag() -> str:
    out = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.strip()


def commit_subjects(since: str) -> List[str]:
    rng = f"{since}..HEAD" if since else "HEAD"
    out = subprocess.run(["git", "log", rng, "--first-parent", "--pretty=%s"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [s for s in out.stdout.splitlines() if s.strip()]


def apply(version: str, entry: str) -> None:
    for path, pattern in VERSION_FILES:
        text = path.read_text(encoding="utf-8")
        new, n = pattern.subn(lambda m: m.group(1) + version + m.group(3), text, count=1)
        if n != 1:
            raise SystemExit(f"no version found in {path.relative_to(ROOT)}")
        path.write_text(new, encoding="utf-8")
    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    head = "# Changelog\n\n"
    changelog.write_text(text.replace(head, head + entry, 1) if text.startswith(head) else head + entry + text, encoding="utf-8")


def main(argv: List[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    version = next_version(current_version(), args[0])
    since = next((a.split("=", 1)[1] for a in argv if a.startswith("--since=")), None) or last_tag()
    entry = changelog_entry(version, commit_subjects(since))
    print(f"{current_version()} -> {version} (changes since {since or 'the start'})\n\n{entry}")
    if "--dry-run" not in argv:
        apply(version, entry)
        print("Updated the four version files and CHANGELOG.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

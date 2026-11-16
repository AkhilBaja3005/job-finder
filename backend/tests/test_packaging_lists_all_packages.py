"""Every Python package in the repo must be listed in pyproject.toml, or the wheel silently omits it.

Regression test: job_finder/commands/ was missing from [tool.setuptools] packages, so an installed wheel
raised ModuleNotFoundError for most CLI commands while running from the source tree worked.
"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOP_LEVEL = ("job_finder", "backend", "applications_tracker")
SKIP_PARTS = {"venv", "node_modules", "tests", "scratch", "__pycache__", "build", "dist", ".venv"}


def _declared_packages():
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    block = re.search(r"\[tool\.setuptools\]\s*packages\s*=\s*\[(.*?)\]", text, re.S).group(1)
    return set(re.findall(r'"([^"]+)"', block))


def _packages_on_disk():
    found = set()
    for top in TOP_LEVEL:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, top)):
            dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS and not d.startswith(".")]
            if "__init__.py" in filenames:
                rel = os.path.relpath(dirpath, ROOT).replace(os.sep, ".")
                found.add(rel)
    return found


def test_all_packages_are_declared_in_pyproject():
    missing = sorted(_packages_on_disk() - _declared_packages())
    assert not missing, f"Add these packages to [tool.setuptools] packages in pyproject.toml: {missing}"

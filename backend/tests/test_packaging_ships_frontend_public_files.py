"""Every file in frontend/public must be matched by pyproject package-data, or the wheel drops it."""
import fnmatch
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_frontend_public_files_are_in_package_data():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        patterns = tomllib.load(f)["tool"]["setuptools"]["package-data"]["*"]
    public = os.path.join(ROOT, "frontend", "public")
    missing = [n for n in os.listdir(public)
               if os.path.isfile(os.path.join(public, n)) and not any(fnmatch.fnmatch(n, p) for p in patterns)]
    assert not missing, f"not shipped in the wheel: {missing}"

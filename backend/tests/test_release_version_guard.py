import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_release_version", ROOT / "scripts" / "check_release_version.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_matching_tag_passes_with_or_without_v():
    assert guard.check("v1.9.2", "1.9.2") is None
    assert guard.check("1.9.2", "1.9.2") is None


def test_mismatched_tag_is_reported():
    assert "does not match" in guard.check("v1.9.3", "1.9.2")
    assert "does not match" in guard.check("desktop-latest", "1.9.2")


def test_reads_the_real_project_version():
    version = guard.project_version(ROOT / "pyproject.toml")
    assert version[0].isdigit() and guard.main(["x", f"v{version}"]) == 0
    assert guard.main(["x", "v0.0.0"]) == 1

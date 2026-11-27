import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
bv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv)


def test_next_version():
    assert bv.next_version("1.9.3", "patch") == "1.9.4"
    assert bv.next_version("1.9.3", "minor") == "1.10.0"
    assert bv.next_version("1.9.3", "major") == "2.0.0"
    assert bv.next_version("1.9.3", "2.5.1") == "2.5.1"


def test_next_version_rejects_junk():
    try:
        bv.next_version("1.9.3", "huge")
    except SystemExit as exc:
        assert "huge" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_classify_titles():
    assert bv.classify("feat(app): dock Chrome beside the window (#127)") == ("Added", "Dock Chrome beside the window")
    assert bv.classify("fix(scan): stop the 429 storm (#138)") == ("Fixed", "Stop the 429 storm")
    assert bv.classify("ci: one-button Release workflow (#144)") is None
    assert bv.classify("release: 1.9.3 (#143)") is None
    assert bv.classify("Merge pull request #5 from x/y") is None
    assert bv.classify("Desktop app works only after Google sign-in (server and app) (#121)") == ("Changed", "Desktop app works only after Google sign-in (server and app)")


def test_changelog_entry_groups_and_dedupes():
    entry = bv.changelog_entry("1.9.4", ["feat: a thing (#1)", "fix: a bug (#2)", "fix: a bug (#3)", "ci: x (#4)"])
    assert entry.startswith("## 1.9.4\n")
    assert "### Added\n- A thing" in entry and entry.count("- A bug") == 1 and "ci" not in entry
    assert "Maintenance release" in bv.changelog_entry("1.9.4", ["ci: x"])


def test_apply_updates_all_four_files_and_changelog(tmp_path, monkeypatch):
    files = {
        "pyproject.toml": 'name = "x"\nversion = "1.9.3"\n',
        "backend/config/constants.py": 'APP_VERSION = "1.9.3"\n',
        "job_finder/__init__.py": '__version__ = "1.9.3"\n',
        "backend/job_finder_mcp/__init__.py": '__version__ = "1.9.3"\n',
        "CHANGELOG.md": "# Changelog\n\n## 1.9.3\n\nold\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    monkeypatch.setattr(bv, "ROOT", tmp_path)
    monkeypatch.setattr(bv, "VERSION_FILES", [(tmp_path / rel, pat) for (_, pat), rel in zip(bv.VERSION_FILES, list(files)[:4])])
    bv.apply("1.9.4", "## 1.9.4\n\n- new\n\n")
    for rel in list(files)[:4]:
        assert "1.9.4" in (tmp_path / rel).read_text() and "1.9.3" not in (tmp_path / rel).read_text()
    assert (tmp_path / "CHANGELOG.md").read_text().startswith("# Changelog\n\n## 1.9.4\n\n- new\n\n## 1.9.3")


def test_the_four_version_files_agree_today():
    versions = {pattern.search(path.read_text()).group(2) for path, pattern in bv.VERSION_FILES}
    assert len(versions) == 1

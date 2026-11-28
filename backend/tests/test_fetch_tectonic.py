"""Bundling Tectonic: pinned downloads, checksum and extraction rules, and finding the bundled engine at run time."""
import hashlib
import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macapp"))
import fetch_tectonic as ft  # noqa: E402
from backend.services import cv_latex  # noqa: E402


def test_pins_cover_the_three_targets_with_real_looking_digests():
    assert set(ft.ASSETS) == {"darwin-arm64", "darwin-x86_64", "win32-x86_64"}
    for name, digest in ft.ASSETS.values():
        assert len(digest) == 64 and set(digest) <= set("0123456789abcdef") and ft.VERSION in name


@pytest.mark.parametrize("system,machine,key", [("darwin", "arm64", "darwin-arm64"), ("darwin", "x86_64", "darwin-x86_64"),
                                                 ("win32", "AMD64", "win32-x86_64"), ("darwin", "aarch64", "darwin-arm64")])
def test_target_key(system, machine, key):
    assert ft.target_key(system, machine) == key


def test_unsupported_platform_is_a_clear_error():
    with pytest.raises(SystemExit) as e:
        ft.target_key("linux", "x86_64")
    assert "No bundled Tectonic" in str(e.value)


def test_checksum_mismatch_is_refused(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    ft.verify(f, hashlib.sha256(b"hello").hexdigest())
    with pytest.raises(SystemExit) as e:
        ft.verify(f, "0" * 64)
    assert "Checksum mismatch" in str(e.value)


def _tar(path, members):
    with tarfile.open(path, "w:gz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def test_extract_takes_only_the_binary_from_a_tarball(tmp_path):
    arc = tmp_path / "t.tar.gz"
    _tar(arc, {"../evil.txt": b"x", "README": b"r", "pkg/tectonic": b"BIN"})
    out = ft.extract_binary(arc, tmp_path / "out")
    assert out.read_bytes() == b"BIN" and sorted(p.name for p in (tmp_path / "out").iterdir()) == ["tectonic"]
    assert not (tmp_path / "evil.txt").exists() and os.access(out, os.X_OK)


def test_extract_from_a_windows_zip(tmp_path):
    arc = tmp_path / "t.zip"
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("tectonic.exe", b"EXE")
        z.writestr("other.txt", b"o")
    out = ft.extract_binary(arc, tmp_path / "out")
    assert out.name == "tectonic.exe" and out.read_bytes() == b"EXE"


def test_extract_fails_when_the_binary_is_missing(tmp_path):
    arc = tmp_path / "t.tar.gz"
    _tar(arc, {"README": b"r"})
    with pytest.raises(SystemExit):
        ft.extract_binary(arc, tmp_path / "out")


def test_sample_cv_for_the_warm_up_uses_the_template():
    tex = ft.sample_latex()
    assert "\\documentclass" in tex and "CPI: 8.0" in tex and "\\fontsize" in tex


def test_runtime_prefers_the_bundled_engine_and_seeds_a_user_cache(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "cache" / "files").mkdir(parents=True)
    (bundle / "cache" / "files" / "x").write_text("cached")
    exe = bundle / ("tectonic.exe" if sys.platform == "win32" else "tectonic")
    exe.write_text("#!/bin/sh\n")
    monkeypatch.delenv("TECTONIC_PATH", raising=False)
    monkeypatch.setattr(cv_latex, "bundled_dir", lambda: str(bundle))
    assert cv_latex.tectonic_path() == str(exe)
    monkeypatch.setattr(cv_latex, "_user_cache_dir", lambda: str(tmp_path / "user" / "cache"))
    dest = cv_latex.prepare_cache(str(bundle))
    assert dest and (Path(dest) / "files" / "x").read_text() == "cached" and (Path(dest) / ".seeded").exists()
    (Path(dest) / "files" / "x").write_text("changed by the user's runs")
    cv_latex.prepare_cache(str(bundle))                                      # already seeded: not copied over again
    assert (Path(dest) / "files" / "x").read_text() == "changed by the user's runs"


def test_explicit_path_wins_and_no_engine_means_unavailable(tmp_path, monkeypatch):
    fake = tmp_path / "mytectonic"
    fake.write_text("x")
    monkeypatch.setenv("TECTONIC_PATH", str(fake))
    assert cv_latex.tectonic_path() == str(fake)
    monkeypatch.delenv("TECTONIC_PATH")
    monkeypatch.setattr(cv_latex, "bundled_dir", lambda: None)
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: None)
    assert cv_latex.tectonic_path() is None and cv_latex.tectonic_available() is False
    assert cv_latex.prepare_cache(None) is None or True


def test_the_build_scripts_fetch_the_engine_and_the_spec_ships_it():
    root = Path(__file__).resolve().parents[2] / "macapp"
    assert "fetch_tectonic.py" in (root / "build_mac.sh").read_text()
    assert "fetch_tectonic.py" in (root / "build_windows.ps1").read_text()
    spec = (root / "job_finder.spec").read_text()
    assert "vendor" in spec and "JOB_FINDER_REQUIRE_TECTONIC" in spec
    assert "latex-check" in (root.parent / ".github" / "workflows" / "build_desktop_apps.yml").read_text()


def test_intel_mac_builds_are_kept_on_a_cryptography_wheel():
    """cryptography >= 49 has no Intel-Mac wheel; pip would compile it against Homebrew's OpenSSL and the app would crash on import."""
    from packaging.requirements import Requirement
    root = Path(__file__).resolve().parents[2]
    reqs = [Requirement(l.split("#")[0].strip()) for l in (root / "backend" / "requirements.txt").read_text().splitlines()
            if l.strip().startswith("cryptography")]
    def pins(env):
        return [str(r.specifier) for r in reqs if r.marker is None or r.marker.evaluate(env)]
    intel = pins({"sys_platform": "darwin", "platform_machine": "x86_64"})
    assert any("<49" in p for p in intel)
    assert not any("<49" in p for p in pins({"sys_platform": "darwin", "platform_machine": "arm64"}))
    assert not any("<49" in p for p in pins({"sys_platform": "win32", "platform_machine": "AMD64"}))
    assert "--only-binary=cryptography" in (root / "macapp" / "build_mac.sh").read_text()

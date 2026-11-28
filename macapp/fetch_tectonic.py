"""Downloads the pinned Tectonic (the LaTeX engine) for this computer into macapp/vendor/tectonic, checks its SHA-256 against
the value pinned below, and warms its package cache with the CV template, so the built app compiles the LaTeX CV offline.

    python macapp/fetch_tectonic.py            # build step: download, verify, extract, warm the cache
    python macapp/fetch_tectonic.py --no-warm  # skip the cache warm-up
    python macapp/fetch_tectonic.py --check    # verify the pins only (no download)

The checksums are the ones GitHub publishes for the official release assets (tectonic-typesetting/tectonic, tag tectonic@0.16.9).
When you move to a newer Tectonic, change VERSION and the three digests together."""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

VERSION = "0.16.9"
BASE = "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40" + VERSION
ASSETS: Dict[str, Tuple[str, str]] = {
    "darwin-arm64": (f"tectonic-{VERSION}-aarch64-apple-darwin.tar.gz", "edb67c61aba768289f6da441c9e6f523cfaff4f8b2a5708523ef29c543f8e88e"),
    "darwin-x86_64": (f"tectonic-{VERSION}-x86_64-apple-darwin.tar.gz", "79d8839fa3594bfea9b2bf2ac0a0455bcc4d0de956a5e5c403107e9a72f79e86"),
    "win32-x86_64": (f"tectonic-{VERSION}-x86_64-pc-windows-msvc.zip", "131a24604785a9600989a3d91225f597df52ac06f00aeffe86fd529f99ee5cdd"),
}
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "vendor" / "tectonic"


def target_key(system: Optional[str] = None, machine: Optional[str] = None) -> str:
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64" if machine in ("x86_64", "amd64") else machine
    key = f"{'win32' if system.startswith('win') else 'darwin' if system.startswith('darwin') else system}-{arch}"
    if key not in ASSETS:
        raise SystemExit(f"No bundled Tectonic for {key}. Supported: {', '.join(ASSETS)}.")
    return key


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify(path: Path, expected: str) -> None:
    got = sha256_of(path)
    if got != expected:
        raise SystemExit(f"Checksum mismatch for {path.name}: expected {expected}, got {got}. Not using it.")


def extract_binary(archive: Path, dest_dir: Path) -> Path:
    """Pull exactly one file (tectonic or tectonic.exe) out of the archive; nothing else is written."""
    wanted = "tectonic.exe" if archive.suffix == ".zip" else "tectonic"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / wanted
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            name = next((n for n in z.namelist() if Path(n).name == wanted and not n.endswith("/")), None)
            if not name:
                raise SystemExit(f"{wanted} not found in {archive.name}")
            with z.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    else:
        with tarfile.open(archive) as t:
            member = next((m for m in t.getmembers() if m.isfile() and Path(m.name).name == wanted), None)
            if not member:
                raise SystemExit(f"{wanted} not found in {archive.name}")
            src = t.extractfile(member)
            assert src is not None
            with src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    dest.chmod(0o755)
    return dest


def sample_latex() -> str:
    """A CV that uses every package and font the template needs, so the cache holds them all."""
    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
    from backend.services import cv_latex
    cv = {"name": "Sample Person", "email": "a@b.co", "phone": "+44 1", "links": ["https://github.com/x/y"],
          "summary": "Engineer with 3+ years building systems used by 1,000+ people.",
          "experience": [{"company": "Acme", "role": "Engineer", "start_date": "Jan 2022", "end_date": "Dec 2024", "technologies": "Python, C++",
                          "description": ["Cut latency by 60% & raised accuracy by 46%.", "Built a RAG assistant for 1,300+ employees."]}],
          "education": [{"institution": "Uni", "degree": "BSc", "start_date": "2019", "graduation_date": "2023", "grade": "CPI: 8.0 / 10.0",
                         "location": "London, UK", "highlights": ["Relevant coursework: Responsible AI", "Placement Coordinator: led outreach."]}],
          "projects": [{"title": "Tool", "technologies": ["Python"], "url": "https://github.com/x/y", "description": ["Built a tool."]}],
          "skills": ["Python"], "skill_groups": {"Languages": ["Python", "C++"], "AI/ML & GenAI": ["LLMs", "RAG"]}}
    tex = cv_latex.cv_to_latex(cv)
    return cv_latex.apply_spacing_scale(tex, 0.9, 10.0)


def warm_cache(exe: Path, cache_dir: Path) -> None:
    import tempfile
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(ROOT / "backend" / "assets" / "resume.cls", tmp)
        Path(tmp, "warm.tex").write_text(sample_latex(), encoding="utf-8")
        run = subprocess.run([str(exe), "warm.tex"], cwd=tmp, env={**os.environ, "TECTONIC_CACHE_DIR": str(cache_dir)},
                             capture_output=True, text=True, timeout=600)
        if run.returncode != 0 or not Path(tmp, "warm.pdf").is_file():
            raise SystemExit("Warming the Tectonic cache failed:\n" + (run.stderr or run.stdout)[-1500:])
    # prove it works offline, from the cache alone
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(ROOT / "backend" / "assets" / "resume.cls", tmp)
        Path(tmp, "check.tex").write_text(sample_latex(), encoding="utf-8")
        run = subprocess.run([str(exe), "--only-cached", "check.tex"], cwd=tmp, env={**os.environ, "TECTONIC_CACHE_DIR": str(cache_dir)},
                             capture_output=True, text=True, timeout=300)
        if run.returncode != 0:
            raise SystemExit("The warmed cache does not compile offline:\n" + (run.stderr or run.stdout)[-1500:])


def main(argv: list) -> int:
    if "--check" in argv:
        for key, (name, digest) in ASSETS.items():
            assert len(digest) == 64 and name.endswith((".tar.gz", ".zip")), key
        print("pins ok:", ", ".join(ASSETS))
        return 0
    key = target_key()
    name, digest = ASSETS[key]
    exe = OUT / ("tectonic.exe" if key.startswith("win") else "tectonic")
    marker = OUT / f".version-{VERSION}"
    if exe.is_file() and marker.is_file() and (OUT / "cache").is_dir() and "--force" not in argv:
        print(f"Tectonic {VERSION} already in {OUT}")
        return 0
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT.parent / name
    print(f"Downloading {name} ...")
    urllib.request.urlretrieve(f"{BASE}/{name}", archive)
    verify(archive, digest)
    exe = extract_binary(archive, OUT)
    archive.unlink()
    print("Checksum verified:", digest[:16], "...", subprocess.run([str(exe), "--version"], capture_output=True, text=True).stdout.strip())
    if "--no-warm" not in argv:
        warm_cache(exe, OUT / "cache")
        print("Cache warmed:", sum(f.stat().st_size for f in (OUT / "cache").rglob("*") if f.is_file()) // 1024, "KiB")
    marker.write_text(VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

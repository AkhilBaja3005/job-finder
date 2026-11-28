# PyInstaller spec for Job Finder: "Job Finder.app" on a Mac (macapp/build_mac.sh), a "Job Finder" folder with Job Finder.exe on Windows (macapp/build_windows.ps1).
import re
import sys
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)

SKIP_DIRS = {"venv", "user_data", "tests", "__pycache__", "static_frontend", "output", "uploads", "scratch"}


def data_tree(src: Path, dest: str):
    """Non-Python files under src (templates, fonts, .cls files) keep their folder layout inside the app."""
    items = []
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if path.is_file() and not (set(rel.parts) & SKIP_DIRS) and path.suffix not in (".py", ".pyc"):
            items.append((str(path), str(Path(dest) / rel.parent)))
    return items


datas = data_tree(ROOT / "backend", "backend")
datas += [(str(ROOT / ".env.example"), ".")]
# The window reads its version from this file. Package metadata can be stale on a dev machine, pyproject.toml is not.
(ROOT / ".macbuild").mkdir(exist_ok=True)
(ROOT / ".macbuild" / "VERSION").write_text(VERSION)
datas += [(str(ROOT / ".macbuild" / "VERSION"), ".")]
datas += [(str(p), str(Path("macapp/panel") / p.relative_to(ROOT / "macapp" / "panel").parent))
          for p in (ROOT / "macapp" / "panel").rglob("*") if p.is_file() and "dev" not in p.relative_to(ROOT / "macapp" / "panel").parts]

# The LaTeX engine (Tectonic) and its warmed package cache, fetched by macapp/fetch_tectonic.py, so the LaTeX CV compiles offline.
_tectonic = ROOT / "macapp" / "vendor" / "tectonic"
if _tectonic.is_dir():
    datas += [(str(f), str(Path("tectonic") / f.relative_to(_tectonic).parent)) for f in _tectonic.rglob("*") if f.is_file()]
elif os.environ.get("JOB_FINDER_REQUIRE_TECTONIC") == "1":
    raise SystemExit("macapp/vendor/tectonic is missing: run python macapp/fetch_tectonic.py first")

binaries = []
hiddenimports = ["scan_panel", "scheduler", "platform_support", "browser_dock", "websockets.sync.client"]
if sys.platform == "darwin":
    hiddenimports += ["native", "objc", "AppKit", "Foundation", "PyObjCTools.AppHelper"]


def local_modules(base: Path, prefix: str = ""):
    """Dotted names of every .py file under base, found on disk. Unlike collect_submodules this imports nothing and
    also finds folders without an __init__.py (job_finder_mcp/tools)."""
    names = []
    for path in base.rglob("*.py"):
        rel = path.relative_to(base)
        if set(rel.parts) & SKIP_DIRS or path.name.startswith("test_") or rel.parts[0] in {"tests", "scratch"}:
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            names.append(".".join(([prefix] if prefix else []) + parts))
    return names


# The backend imports its own modules both by short names (services, routes, ...) and as backend.*.
hiddenimports += local_modules(ROOT / "backend")
hiddenimports += local_modules(ROOT / "backend", "backend")
hiddenimports += ["backend"]
hiddenimports += local_modules(ROOT / "job_finder", "job_finder") + ["job_finder"]
hiddenimports += local_modules(ROOT / "applications_tracker", "applications_tracker") + ["applications_tracker"]

# Packages that load files or metadata at run time.
for pkg in ("browser_use", "playwright", "cdp_use", "bubus", "webview", "google.genai", "tiktoken", "certifi", "pypdfium2"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # a package that is not installed is simply left out
        print(f"[spec] skipping {pkg}: {exc}")
for dist in ("browser-use", "fastapi", "uvicorn", "pydantic", "anthropic", "openai", "google-genai", "posthog"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

a = Analysis(  # noqa: F821
    [str(ROOT / "macapp" / "job_finder_app.py")],
    pathex=[str(ROOT), str(ROOT / "backend"), str(ROOT / "macapp")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "pyright"],
)
pyz = PYZ(a.pure)  # noqa: F821
if sys.platform == "win32":
    icon_png = ROOT / "macapp" / "icon.png"  # PyInstaller turns the PNG into an .ico when Pillow is installed
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [], exclude_binaries=True, name="Job Finder", console=False, icon=str(icon_png) if icon_png.exists() else None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Job Finder")  # noqa: F821
else:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [], exclude_binaries=True, name="Job Finder", console=False, argv_emulation=False,
    )
    # The same program built as a console tool. The window starts it for every scan, install and daily run; being a console
    # program it does not register as an app, so it never bounces in the Dock.
    exe_cli = EXE(  # noqa: F821
        pyz, a.scripts, [], exclude_binaries=True, name="job-finder-cli", console=True, argv_emulation=False,
    )
    coll = COLLECT(exe, exe_cli, a.binaries, a.datas, name="Job Finder")  # noqa: F821
    app = BUNDLE(  # noqa: F821
        coll,
        name="Job Finder.app",
        icon=str(ROOT / "macapp" / "icon.icns") if (ROOT / "macapp" / "icon.icns").exists() else None,
        bundle_identifier="space.job-finder.app",
        version=VERSION,
        info_plist={
            "CFBundleName": "Job Finder",
            "CFBundleDisplayName": "Job Finder",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )

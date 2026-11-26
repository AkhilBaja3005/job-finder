# PyInstaller spec for "Job Finder.app". Build with macapp/build_mac.sh.
import re
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
datas += [(str(ROOT / ".env.example"), "."), (str(ROOT / "macapp" / "panel"), "macapp/panel")]

binaries = []
hiddenimports = ["scan_panel"]


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
for pkg in ("browser_use", "playwright", "cdp_use", "bubus", "webview", "google.genai", "tiktoken", "certifi"):
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
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="Job Finder", console=False, argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Job Finder")  # noqa: F821
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

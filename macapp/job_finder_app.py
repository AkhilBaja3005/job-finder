"""
Job Finder for macOS: a control panel for the job scanner and auto-apply agent.

Pick roles and limits, press Start, and watch the agent search and fill applications. It runs the same
`job-finder scan` the command line tool does, so results are identical.

    python macapp/job_finder_app.py                 # open the window
    python macapp/job_finder_app.py --cli scan ...  # run the command line tool (the window uses this for each run)
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_panel  # noqa: E402  (same folder; PyInstaller finds it through the import above)


def bundle_root() -> Path:
    """The folder with the app's files: the PyInstaller bundle, or the repo when run from source."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def launcher_command() -> list[str]:
    """The command that runs the command line tool: this same program with --cli."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cli"]
    return [sys.executable, str(Path(__file__).resolve()), "--cli"]


def prepare_environment() -> Path:
    """Points the tool at the user's folder, puts the bundled code on the path, and loads the .env. Returns the folder."""
    workspace = scan_panel.workspace_dir()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["JOB_FINDER_ROOT"] = str(workspace)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(scan_panel.app_support_dir() / "browsers"))

    root = bundle_root()
    for path in (root, root / "backend"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    env_file = workspace / ".env"
    if not env_file.exists():
        example = root / ".env.example"
        env_file.write_text(example.read_text(encoding="utf-8") if example.exists() else "# Job Finder settings\n", encoding="utf-8")
        env_file.chmod(0o600)  # it will hold API keys
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
    except ImportError:
        pass
    os.chdir(workspace)
    return workspace


def run_cli(argv: list[str]) -> int:
    prepare_environment()
    sys.argv = ["job-finder"] + argv
    from job_finder.cli import main
    main()
    return 0


def ensure_browser_in_background() -> None:
    """Downloads the Chromium the page scraper uses, once, without blocking the window."""
    if os.environ.get("JOB_FINDER_SKIP_BROWSER_INSTALL") == "1":
        return
    browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", scan_panel.app_support_dir() / "browsers"))
    if any(browsers.glob("chromium-*")):
        return

    def _install() -> None:
        try:
            from playwright._impl._driver import compute_driver_executable, get_driver_env
            node, cli = compute_driver_executable()
            subprocess.run([str(node), str(cli), "install", "chromium"], env=get_driver_env(), check=False, timeout=900)
        except Exception as exc:  # the scraper falls back to other methods, so this is not fatal
            print(f"[job-finder-app] Could not install the scraper browser: {exc}")

    threading.Thread(target=_install, name="playwright-install", daemon=True).start()


def run_window() -> int:
    import webview
    from webview.menu import Menu, MenuAction

    workspace = prepare_environment()
    api = scan_panel.Api(launcher_command())
    html = bundle_root() / "macapp" / "panel" / "index.html"
    if not html.exists():  # bundled layout
        html = bundle_root() / "panel" / "index.html"
    window = webview.create_window("Job Finder", str(html), js_api=api, width=1100, height=860, min_size=(820, 620))
    api._bind(window)
    menu = [Menu("Job Finder", [
        MenuAction("Open data folder", lambda: subprocess.run(["open", str(workspace)])),
        MenuAction("Edit settings (.env)", lambda: subprocess.run(["open", "-t", str(workspace / ".env")])),
    ])]
    ensure_browser_in_background()
    webview.start(menu=menu)
    api.stop_scan()  # closing the window ends any run that is still going
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--cli":
        return run_cli(argv[1:])
    return run_window()


if __name__ == "__main__":
    sys.exit(main())

"""
Job Finder for macOS: a control panel for the job scanner and auto-apply agent.

Pick roles and limits, press Start, and watch the agent search and fill applications. It runs the same
`job-finder scan` the command line tool does, so results are identical.

    python macapp/job_finder_app.py                 # open the window
    python macapp/job_finder_app.py --cli scan ...  # run the command line tool (the window uses this for each run)
"""
from __future__ import annotations

import platform_support
import logging
import logging.handlers
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_panel  # noqa: E402  (same folder; PyInstaller finds it through the import above)


def bundle_root() -> Path:
    """The folder with the app's files: the PyInstaller bundle, or the repo when run from source."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def launcher_command() -> list[str]:
    """The command that runs the command line tool: this same program with --cli."""
    if getattr(sys, "frozen", False):
        # On a Mac the windowed program registers as an app, so every child of it would bounce in the Dock. The bundle also
        # holds a console build of the same program (job-finder-cli) for background work, which stays out of the Dock.
        cli = Path(sys.executable).with_name("job-finder-cli")
        return [str(cli) if cli.exists() else sys.executable, "--cli"]
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


def install_browser() -> int:
    """Downloads the Chromium the page scraper uses (what `playwright install chromium` does)."""
    prepare_environment()
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    node, cli = compute_driver_executable()
    return subprocess.run([str(node), str(cli), "install", "chromium"], env=get_driver_env(), check=False).returncode


SIGNIN_PAGES = ("https://www.linkedin.com/login", "https://secure.indeed.com/auth", "https://www.reed.co.uk/account/signin")


def open_in_agent_chrome(url: str) -> int:
    """Opens one job page in the agent's Chrome profile (where the user is signed in), for checking a form by hand."""
    if not url.startswith(("http://", "https://")):
        return 2
    prepare_environment()
    import urllib.parse
    import urllib.request
    from services.browser_use_agent import ensure_persistent_browser
    cdp = ensure_persistent_browser(headless=False)
    try:
        urllib.request.urlopen(urllib.request.Request(f"{cdp}/json/new?{urllib.parse.quote(url, safe=':/?&=%#')}", method="PUT"), timeout=5).read()
    except Exception:
        return 1
    return 0


def open_signin_browser() -> int:
    """Opens the agent's own Chrome profile with the job sites' sign-in pages, so the user can log in once.
    The agent reuses this profile, so the sign-ins carry over to every run."""
    prepare_environment()
    import urllib.request
    from services.browser_use_agent import ensure_persistent_browser
    cdp = ensure_persistent_browser(headless=False)
    for page in SIGNIN_PAGES:
        try:  # DevTools opens a tab with PUT /json/new?<url>
            urllib.request.urlopen(urllib.request.Request(f"{cdp}/json/new?{page}", method="PUT"), timeout=5).read()
        except Exception:
            pass
    return 0


def setup_logging() -> None:
    """The app's own log, next to the per-run logs: ~/Library/Logs/Job Finder/app.log (rotated)."""
    directory = scan_panel.logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(directory / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    def hook(kind, value, trace):
        logging.getLogger("job_finder_app").critical("Uncaught error", exc_info=(kind, value, trace))
        sys.__excepthook__(kind, value, trace)
    sys.excepthook = hook


def acquire_single_instance():
    """Only one window at a time. Returns the lock file object (keep it alive), or None when the app is already open."""
    scan_panel.app_support_dir().mkdir(parents=True, exist_ok=True)
    handle = open(scan_panel.app_support_dir() / "app.lock", "w")
    if not platform_support.lock_file(handle):
        handle.close()
        return None
    return handle


def selftest(window, log) -> None:
    """Loads the page, reports what rendered, and closes. For checking a build: JOB_FINDER_APP_SELFTEST=1."""
    import json
    import time
    probe = ("JSON.stringify({script: typeof window.__jf, nav: document.querySelectorAll('#nav button').length, "
             "title: (document.querySelector('h1') || {}).textContent || '', "
             "css: getComputedStyle(document.querySelector('.sidebar') || document.body).display, "
             "icons: document.querySelectorAll('svg').length, info: !!(window.__jf && window.__jf.hasInfo()), bridge: typeof (window.pywebview && window.pywebview.api && window.pywebview.api.get_state)})")
    result: dict = {}
    for _ in range(20):  # the page needs a moment to start
        time.sleep(0.5)
        try:
            raw = window.evaluate_js(probe)
            result = json.loads(raw) if raw else {"error": "no answer from the page"}
            if result.get("nav") and result.get("info"):
                break
        except Exception as exc:
            result = {"error": str(exc)[:200]}
    log.info("SELFTEST %s", json.dumps(result))
    print("SELFTEST", json.dumps(result), flush=True)
    window.destroy()


def run_window() -> int:
    import webview

    lock = acquire_single_instance()
    if lock is None:
        platform_support.activate_running_app("Job Finder")
        print("Job Finder is already open.")
        return 0
    setup_logging()
    log = logging.getLogger("job_finder_app")
    workspace = prepare_environment()
    log.info("Starting Job Finder %s, folder %s", scan_panel._app_version(), workspace)

    api = scan_panel.Api(launcher_command())
    html = bundle_root() / "macapp" / "panel" / "index.html"
    if not html.exists():  # bundled layout
        html = bundle_root() / "panel" / "index.html"

    config = scan_panel.load_app_config()
    size = config.get("window") or {}
    width, height = int(size.get("width", 1180)), int(size.get("height", 820))
    window = webview.create_window("Job Finder", str(html), js_api=api, width=max(width, 940), height=max(height, 600), min_size=(940, 600),
                                   background_color="#FFFFFF", text_select=True)
    api._bind(window)

    def remember_size(new_width: int, new_height: int) -> None:
        cfg = scan_panel.load_app_config()
        cfg["window"] = {"width": int(new_width), "height": int(new_height)}
        scan_panel.save_app_config(cfg)
    window.events.resized += remember_size

    def on_closing() -> None:
        api.stop_scan()
    window.events.closing += on_closing

    def show(page_js: str) -> None:
        try:
            window.evaluate_js(page_js)
        except Exception:
            log.exception("could not reach the page")

    def after_start() -> None:
        if platform_support.IS_MAC:
            import native
            native.style_window(window)
            native.install_menu("Job Finder", {
                "settings": lambda: show("window.__jf && window.__jf.go('settings')"),
                "updates": lambda: show("window.__jf && window.__jf.checkUpdate()"),
                "folder": lambda: api.open_path("workspace"),
                "logs": lambda: api.open_path("logs"),
                "website": lambda: webbrowser.open("https://github.com/AkhilBaja3005/job-finder"),
            })
        api.ensure_browser()
        if os.environ.get("JOB_FINDER_APP_SELFTEST") == "1":
            selftest(window, log)

    webview.start(after_start)
    api.stop_scan()  # closing the window ends any run that is still going
    log.info("Job Finder closed")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:  # a built app has no system certificate list; child processes inherit this too
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:
        pass
    if argv and argv[0] == "--cli":
        return run_cli(argv[1:])
    if argv and argv[0] == "--install-browser":
        return install_browser()
    if argv and argv[0] == "--open" and len(argv) > 1:
        return open_in_agent_chrome(argv[1])
    if argv and argv[0] == "--signin":
        return open_signin_browser()
    return run_window()


if __name__ == "__main__":
    sys.exit(main())

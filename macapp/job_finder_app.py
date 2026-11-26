"""
Job Finder for macOS.

Starts the Job Finder server on this Mac and shows the web app in its own window.
Your data (settings, resume, tracker) lives in ~/Library/Application Support/Job Finder,
never inside the app, so updating or deleting the app does not touch it.

    python macapp/job_finder_app.py              # open the window
    python macapp/job_finder_app.py --no-window  # start the server only, print the address
    python macapp/job_finder_app.py --check      # start, test the server, exit (for CI)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

APP_NAME = "Job Finder"
DEFAULT_PORT = 8000  # the web app and the Chrome extension both expect 127.0.0.1:8000
SERVICE_NAME = "job-finder-backend"


def bundle_root() -> Path:
    """The folder with the app's files: the PyInstaller bundle, or the repo when run from source."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def support_dir() -> Path:
    override = os.environ.get("JOB_FINDER_APP_HOME")
    return Path(override) if override else Path.home() / "Library" / "Application Support" / APP_NAME


def prepare_environment() -> Path:
    """Points the server at the user's data folder and loads their .env. Returns the data folder."""
    home = support_dir()
    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("JOB_FINDER_ROOT", str(home))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(home / "browsers"))

    root = bundle_root()
    for path in (root, root / "backend"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    env_file = home / ".env"
    if not env_file.exists():
        example = root / ".env.example"
        env_file.write_text(example.read_text(encoding="utf-8") if example.exists() else "# Job Finder settings\n", encoding="utf-8")
        env_file.chmod(0o600)  # it will hold API keys
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
    except ImportError:
        pass
    os.environ["HOST"] = "127.0.0.1"  # after the .env, so a setting there cannot open the server to the network
    os.chdir(home)
    return home


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _is_job_finder(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
            return json.load(resp).get("service") == SERVICE_NAME
    except Exception:
        return False


def pick_port(preferred: int = DEFAULT_PORT) -> tuple[int, bool]:
    """(port, already_running). Reuses a Job Finder server that is already on the port."""
    if _port_is_free(preferred):
        return preferred, False
    if _is_job_finder(preferred):
        return preferred, True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1], False


def start_server(port: int):
    """Runs the FastAPI server in a background thread and returns the uvicorn server object."""
    import uvicorn
    from backend.main import app  # imported late so the environment is set first

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name="job-finder-server", daemon=True).start()
    return server


def wait_until_ready(port: int, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_job_finder(port):
            return True
        time.sleep(0.4)
    return False


def ensure_browser_in_background(home: Path) -> None:
    """Downloads the Chromium the page scraper uses, once, without blocking the window."""
    if os.environ.get("JOB_FINDER_SKIP_BROWSER_INSTALL") == "1":
        return
    browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", home / "browsers"))
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


def run_window(url: str, home: Path) -> None:
    import webview
    from webview.menu import Menu, MenuAction

    env_file = home / ".env"
    menu = [Menu(APP_NAME, [
        MenuAction("Open data folder", lambda: subprocess.run(["open", str(home)])),
        MenuAction("Edit settings (.env)", lambda: subprocess.run(["open", "-t", str(env_file)])),
        MenuAction("Open in browser", lambda: webbrowser.open(url)),
    ])]
    webview.create_window(APP_NAME, url, width=1360, height=900, min_size=(900, 640))
    webview.start(menu=menu)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument("--no-window", action="store_true", help="start the server without opening a window")
    parser.add_argument("--check", action="store_true", help="start the server, test it, and exit")
    args = parser.parse_args(argv)

    home = prepare_environment()
    port, already_running = pick_port(args.port)
    server = None
    if not already_running:
        print(f"[job-finder-app] Starting the server on 127.0.0.1:{port} (data: {home})")
        server = start_server(port)
    if not wait_until_ready(port):
        print("[job-finder-app] The server did not start in time. See the log above.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"

    if args.check:
        with urllib.request.urlopen(url, timeout=10) as resp:
            ok = resp.status == 200 and b"<div id=\"root\"" in resp.read()
        print("[job-finder-app] check:", "OK" if ok else "the web app page did not load")
        if server:
            server.should_exit = True
        return 0 if ok else 1

    ensure_browser_in_background(home)
    if args.no_window:
        print(f"[job-finder-app] Ready at {url}  (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        run_window(url, home)
    if server:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())

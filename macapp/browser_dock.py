"""Docked browser: the agent's Chrome sits flush against the right edge of the Job Finder window and follows it.

Real embedding is not possible with pywebview: on macOS it is WKWebView, which has no DevTools protocol for browser-use to
attach to, and Google refuses sign-in inside embedded web views. So the agent keeps its own signed-in Chrome, and this module
places that window next to the app window (and moves it when the app window moves) through Chrome's own
Browser.setWindowBounds call. That call works the same on macOS and Windows and needs no extra permission.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("job_finder_app")

Bounds = Tuple[int, int, int, int]  # x, y, width, height
MIN_BROWSER_WIDTH = 520


def dock_bounds(window: Bounds, screen: Bounds) -> Bounds:
    """Where Chrome goes: right of the app window, same height. When the screen has no room on the right, Chrome takes
    the right-hand part of the screen it still can (never narrower than MIN_BROWSER_WIDTH) and overlaps the app window."""
    wx, wy, ww, wh = window
    sx, sy, sw, sh = screen
    top = max(sy, min(wy, sy + sh - 300))
    height = max(300, min(wh, sy + sh - top))
    left = wx + ww
    width = sx + sw - left
    if width < MIN_BROWSER_WIDTH:
        width = min(MIN_BROWSER_WIDTH, sw)
        left = sx + sw - width
    return int(left), int(top), int(width), int(height)


def bounds_env(bounds: Bounds) -> str:
    return ",".join(str(int(v)) for v in bounds)


def parse_bounds_env(value: Optional[str]) -> Optional[Bounds]:
    """The inverse of bounds_env. None for anything that is not four positive-size numbers."""
    try:
        x, y, w, h = (int(p) for p in str(value or "").split(","))
    except ValueError:
        return None
    return (x, y, w, h) if w >= 200 and h >= 200 else None


def chrome_window_args(value: Optional[str]) -> list:
    """Chrome command-line flags that open its window at the docked position."""
    b = parse_bounds_env(value)
    return [f"--window-position={b[0]},{b[1]}", f"--window-size={b[2]},{b[3]}"] if b else []


def _cdp_json(cdp_url: str, path: str) -> Any:
    with urllib.request.urlopen(f"{cdp_url}{path}", timeout=2) as resp:
        return json.load(resp)


def move_chrome(cdp_url: str, bounds: Bounds) -> bool:
    """Moves the Chrome behind cdp_url to bounds. False when it is not running or refuses."""
    try:
        version = _cdp_json(cdp_url, "/json/version")
        from websockets.sync.client import connect  # websockets is a browser-use dependency
        ws = connect(version["webSocketDebuggerUrl"], open_timeout=3, close_timeout=1)
        try:
            ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            targets = json.loads(ws.recv(timeout=3)).get("result", {}).get("targetInfos", [])
            page = next((t for t in targets if t.get("type") == "page"), None)
            if page is None:
                return False
            ws.send(json.dumps({"id": 2, "method": "Browser.getWindowForTarget", "params": {"targetId": page["targetId"]}}))
            window_id = json.loads(ws.recv(timeout=3))["result"]["windowId"]
            x, y, w, h = bounds
            ws.send(json.dumps({"id": 3, "method": "Browser.setWindowBounds", "params": {
                "windowId": window_id, "bounds": {"windowState": "normal", "left": x, "top": y, "width": w, "height": h}}}))
            return "error" not in json.loads(ws.recv(timeout=3))
        finally:
            ws.close()
    except Exception:
        log.debug("could not dock Chrome", exc_info=True)
        return False


class Dock:
    """Watches the app window and keeps Chrome docked to it while docking is switched on."""

    def __init__(self, window: Any, cdp_url: str, screen: Bounds, interval: float = 0.6):
        self.window, self.cdp_url, self.screen, self.interval = window, cdp_url, screen, interval
        self._stop = threading.Event()
        self._last: Optional[Bounds] = None
        self._thread: Optional[threading.Thread] = None

    def current_bounds(self) -> Optional[Bounds]:
        try:
            return dock_bounds((int(self.window.x), int(self.window.y), int(self.window.width), int(self.window.height)), self.screen)
        except Exception:
            return None

    def tick(self) -> bool:
        """One check: move Chrome if the app window moved since last time. True when Chrome was moved."""
        bounds = self.current_bounds()
        if bounds is None or bounds == self._last:
            return False
        moved = move_chrome(self.cdp_url, bounds)
        if moved:
            self._last = bounds
        return moved

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.tick()

    def stop(self) -> None:
        self._stop.set()


def screen_bounds(webview_module: Any = None) -> Bounds:
    """The main screen's usable area; a safe default when pywebview cannot say."""
    try:
        screen = (webview_module.screens or [])[0]
        return int(screen.x), int(screen.y), int(screen.width), int(screen.height)
    except Exception:
        return 0, 0, 1920, 1080

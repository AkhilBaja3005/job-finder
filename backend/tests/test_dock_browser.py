"""Docked browser: geometry, env handoff, Chrome launch flags, and the Api only docking when the setting is on."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macapp"))
import browser_dock as dock  # noqa: E402
import scan_panel as panel  # noqa: E402

SCREEN = (0, 0, 1920, 1080)


def test_dock_right_of_window_same_height():
    assert dock.dock_bounds((100, 100, 1000, 700), SCREEN) == (1100, 100, 820, 700)


def test_dock_overlaps_when_no_room():
    x, y, w, h = dock.dock_bounds((300, 50, 1500, 800), SCREEN)
    assert w == dock.MIN_BROWSER_WIDTH and x + w == 1920 and (y, h) == (50, 800)


def test_dock_clamps_to_screen_height():
    x, y, w, h = dock.dock_bounds((0, 900, 900, 900), SCREEN)
    assert y + h <= 1080 and h >= 300


def test_bounds_env_roundtrip_and_rejects_garbage():
    assert dock.parse_bounds_env(dock.bounds_env((1, 2, 800, 600))) == (1, 2, 800, 600)
    for bad in (None, "", "a,b,c,d", "1,2,3", "1,2,50,50"):
        assert dock.parse_bounds_env(bad) is None
    assert dock.chrome_window_args("1,2,800,600") == ["--window-position=1,2", "--window-size=800,600"]
    assert dock.chrome_window_args("x") == []


def test_backend_launch_flags():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.browser_use_agent import _docked_window_args
    assert _docked_window_args("10,20,900,700") == ["--window-position=10,20", "--window-size=900,700"]
    assert _docked_window_args("nonsense") == [] and _docked_window_args(None) == []


def test_tick_moves_only_when_window_moves(monkeypatch):
    calls = []
    monkeypatch.setattr(dock, "move_chrome", lambda url, b: calls.append(b) or True)
    win = MagicMock(x=0, y=0, width=1000, height=700)
    d = dock.Dock(win, "http://127.0.0.1:1", SCREEN, instances=1)
    assert d.tick() is True and d.tick() is False
    win.x = 50
    assert d.tick() is True and len(calls) == 2


def test_tick_retries_when_chrome_not_up(monkeypatch):
    monkeypatch.setattr(dock, "move_chrome", lambda url, b: False)
    d = dock.Dock(MagicMock(x=0, y=0, width=1000, height=700), "http://127.0.0.1:1", SCREEN)
    assert d.tick() is False and d.tick() is False  # still pending, will try again


def test_api_docks_only_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path / "support"))
    (tmp_path / "support").mkdir()
    monkeypatch.setattr(panel, "GATE_ENABLED", False)  # the sign-in gate has its own tests
    api = panel.Api(["x"])
    assert api._dock_env() == {}  # no window
    api._bind(MagicMock(x=0, y=0, width=1000, height=700))
    assert api._dock_env() == {}  # setting off
    api.save_app_prefs({"dock_browser": True})
    started = []
    monkeypatch.setattr(dock.Dock, "start", lambda self: started.append(1))
    env = api._dock_env()
    assert dock.parse_bounds_env(env["JOB_FINDER_DOCK_BOUNDS"]) and started
    api.save_app_prefs({"headless": True})
    assert api._dock_env() == {}  # hidden run: nothing to dock


def test_dock_follows_every_chrome_instance(monkeypatch):
    seen = {}
    running = {"http://127.0.0.1:9223", "http://127.0.0.1:9225"}
    def fake_move(url, b):
        if url in running:
            seen[url] = b
            return True
        return False
    monkeypatch.setattr(dock, "move_chrome", fake_move)
    win = MagicMock(x=0, y=0, width=1000, height=700)
    d = dock.Dock(win, "http://127.0.0.1:9223", SCREEN)
    assert d.tick() is True and set(seen) == running
    running.add("http://127.0.0.1:9224")  # a new Chrome starts later and gets placed on the next check
    assert d.tick() is True and "http://127.0.0.1:9224" in seen
    assert d.tick() is False


def test_windows_toast_command_quotes_text(monkeypatch):
    import platform_support as ps
    cmd = ps.windows_toast_command("Job Finder", "it's done\nnow")
    assert cmd[0] == "powershell.exe" and "'it''s done now'" in cmd[-1]


def test_notify_runs_toast_on_windows_and_is_silent_on_error(monkeypatch):
    import platform_support as ps
    calls = []
    monkeypatch.setattr(ps, "IS_MAC", False)
    monkeypatch.setattr(ps, "IS_WINDOWS", True)
    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    ps.notify("t", "m")
    assert calls and calls[0][0] == "powershell.exe"
    def boom(*a, **k): raise OSError("no powershell")
    monkeypatch.setattr(ps.subprocess, "run", boom)
    ps.notify("t", "m")  # never raises


def test_live_view_only_while_running_and_survives_no_chrome(monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "GATE_ENABLED", False)
    api = panel.Api(["x"])
    assert api.live_view() == {"ok": False}  # nothing running
    monkeypatch.setattr(type(api._runner), "running", property(lambda self: True))
    monkeypatch.setattr(dock, "live_view", lambda urls: {"ok": True, "urls": urls})
    out = api.live_view()
    assert out["ok"] and out["urls"][0].endswith(":9223") and len(out["urls"]) == 20


def test_live_view_returns_data_uri_from_cdp(monkeypatch):
    import base64
    import json as _json

    class FakeWs:
        def send(self, m): self.m = _json.loads(m)
        def recv(self, timeout=None): return _json.dumps({"id": 1, "result": {"data": base64.b64encode(b"jpg").decode()}})
        def close(self): pass
    monkeypatch.setattr(dock, "_cdp_json", lambda url, path: [{"type": "page", "url": "https://x.test/a", "title": "A", "webSocketDebuggerUrl": "ws://x"}])
    import websockets.sync.client as c
    monkeypatch.setattr(c, "connect", lambda *a, **k: FakeWs())
    v = dock.live_view(["http://127.0.0.1:9223"])
    assert v["ok"] and v["image"].startswith("data:image/jpeg;base64,") and v["url"] == "https://x.test/a"
    monkeypatch.setattr(dock, "_cdp_json", lambda url, path: (_ for _ in ()).throw(OSError("down")))
    assert dock.live_view(["http://127.0.0.1:9223"]) == {"ok": False}

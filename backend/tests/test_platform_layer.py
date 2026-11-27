"""The platform layer, the schedulers and the Dock helper: each branch, including the ones that only run on another operating system."""
import os
import plistlib
import subprocess
import sys
import types
from pathlib import Path

import pytest

MACAPP = Path(__file__).resolve().parents[2] / "macapp"
sys.path.insert(0, str(MACAPP))
import platform_support as ps  # noqa: E402
import scheduler  # noqa: E402
from utils import dock  # noqa: E402


def as_platform(monkeypatch, name):
    monkeypatch.setattr(ps, "IS_MAC", name == "mac")
    monkeypatch.setattr(ps, "IS_WINDOWS", name == "windows")


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess(["x"], code, out, err)


# ── folders and Chrome on each system ────────────────────────────────────────────
def test_linux_folders_follow_the_xdg_variables_or_fall_back_to_home(monkeypatch, tmp_path):
    as_platform(monkeypatch, "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert ps.app_support_dir("Job Finder") == tmp_path / "data" / "Job Finder"
    assert ps.logs_base("Job Finder") == tmp_path / "state" / "Job Finder" / "logs"
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.delenv("XDG_STATE_HOME")
    assert ps.app_support_dir("Job Finder").parts[-3:] == (".local", "share", "Job Finder")
    assert ps.logs_base("Job Finder").parts[-4:] == (".local", "state", "Job Finder", "logs")


def test_windows_folders_fall_back_when_the_variables_are_missing(monkeypatch):
    as_platform(monkeypatch, "windows")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert ps.app_support_dir("Job Finder").parts[-3:] == ("AppData", "Roaming", "Job Finder")
    assert ps.logs_base("Job Finder").parts[-4:] == ("AppData", "Local", "Job Finder", "Logs")


def test_chrome_places_per_system(monkeypatch):
    as_platform(monkeypatch, "mac")
    assert any(p.endswith("Google Chrome.app") for p in ps.chrome_candidates())
    as_platform(monkeypatch, "linux")
    assert ps.chrome_candidates() == []
    as_platform(monkeypatch, "windows")
    monkeypatch.setenv("PROGRAMFILES", "C:\\Program Files")
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\a\\AppData\\Local")
    names = ps.chrome_candidates()
    assert len(names) == 2 and all(n.endswith("chrome.exe") for n in names)


def test_chrome_on_the_path_counts(monkeypatch):
    as_platform(monkeypatch, "linux")
    monkeypatch.setattr(ps.shutil, "which", lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None)
    assert ps.chrome_found() is True
    monkeypatch.setattr(ps.shutil, "which", lambda name: None)
    assert ps.chrome_found() is False


# ── opening things ───────────────────────────────────────────────────────────────
def test_open_path_per_system(monkeypatch):
    ran = []
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or done())
    as_platform(monkeypatch, "mac")
    ps.open_path("/x/file.txt", as_text=True)
    as_platform(monkeypatch, "linux")
    ps.open_path("/x/folder")
    assert ran == [["open", "-t", "/x/file.txt"], ["xdg-open", "/x/folder"]]
    started = []
    as_platform(monkeypatch, "windows")
    monkeypatch.setattr(os, "startfile", lambda path: started.append(path), raising=False)
    ps.open_path("C:\\x\\folder")
    ps.open_path("C:\\x\\.env", as_text=True)
    assert started == ["C:\\x\\folder"] and ran[-1] == ["notepad.exe", "C:\\x\\.env"]


def test_notifications_on_mac_and_windows_and_never_raise(monkeypatch):
    ran = []
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or done())
    as_platform(monkeypatch, "windows")
    ps.notify("Job Finder", "hello")
    assert ran[0][0] == "powershell.exe"
    ran.clear()
    as_platform(monkeypatch, "linux")
    ps.notify("Job Finder", "hello")
    assert ran == []
    as_platform(monkeypatch, "mac")
    ps.notify("Job Finder", 'say "hi"')
    assert ran[0][:2] == ["osascript", "-e"] and 'say \\"hi\\"' in ran[0][2]
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(OSError("no osascript")))
    ps.notify("Job Finder", "still fine")


def test_bringing_a_running_copy_forward_is_a_mac_only_nicety(monkeypatch):
    ran = []
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or done())
    as_platform(monkeypatch, "linux")
    ps.activate_running_app("Job Finder")
    assert ran == []
    as_platform(monkeypatch, "mac")
    ps.activate_running_app("Job Finder")
    assert 'tell application "Job Finder" to activate' in ran[0][2]


def test_the_one_window_lock_on_windows_uses_msvcrt(monkeypatch, tmp_path):
    as_platform(monkeypatch, "windows")
    calls = []

    def locking(fd, mode, size):
        calls.append((mode, size))
        if len(calls) == 2:
            raise OSError("already locked")

    fake = types.SimpleNamespace(LK_NBLCK=2, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    with open(tmp_path / "lock", "w") as handle:
        assert ps.lock_file(handle) is True
        assert ps.lock_file(handle) is False
    assert calls == [(2, 1), (2, 1)]


# ── the Dock helper ──────────────────────────────────────────────────────────────
def test_dock_helper_handles_missing_libraries_and_failures(monkeypatch):
    monkeypatch.setattr(dock.sys, "platform", "darwin")
    import ctypes.util
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    assert dock.hide_dock_icon() is False                             # no ApplicationServices library: nothing to do
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: (_ for _ in ()).throw(RuntimeError("odd")))
    assert dock.hide_dock_icon() is False                             # any failure is swallowed
    monkeypatch.setattr(dock.sys, "platform", "win32")
    assert dock.hide_dock_icon() is False


# ── the daily run on a Mac ───────────────────────────────────────────────────────
def test_launchctl_is_called_with_a_timeout(monkeypatch):
    seen = {}
    monkeypatch.setattr(scheduler.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or done())
    scheduler._launchctl("print", "gui/501/x")
    assert seen["cmd"] == ["launchctl", "print", "gui/501/x"] and seen["kw"]["timeout"] == 20


def test_mac_install_reports_launchctl_errors_and_replaces_an_old_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def launchctl(*args):
        calls.append(args[0])
        return done(5, "", "Bootstrap failed: 5: Input/output error") if args[0] == "bootstrap" else done()

    monkeypatch.setattr(scheduler, "_launchctl", launchctl)
    out = scheduler.install(8, 30, ["/p", "--cli", "scan", "--dry-run"], tmp_path, tmp_path / "log" / "s.log", {"X": "1"}, home=tmp_path)
    assert out["ok"] is False and "Bootstrap failed" in out["error"] and calls == ["bootout", "bootstrap"]      # the old copy is unloaded first
    assert scheduler.agent_path(tmp_path).exists()
    assert scheduler.install(24, 0, ["/p"], tmp_path, tmp_path / "s.log", home=tmp_path)["ok"] is False


def test_mac_status_remove_and_a_damaged_schedule_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(scheduler, "_launchctl", lambda *a: done())
    assert scheduler.status(home=tmp_path) == {"enabled": False}
    assert scheduler.remove(home=tmp_path) == {"ok": True}                                    # removing what is not there is fine
    path = scheduler.agent_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a plist")
    assert scheduler.status(home=tmp_path) == {"enabled": False}
    path.write_bytes(plistlib.dumps({"Label": scheduler.LABEL, "ProgramArguments": ["/p", "--auto-apply"], "StartCalendarInterval": {"Hour": 6, "Minute": 5}}))
    assert scheduler.status(home=tmp_path) == {"enabled": True, "hour": 6, "minute": 5, "real": True}
    path.write_bytes(plistlib.dumps({"Label": scheduler.LABEL}))
    assert scheduler.status(home=tmp_path) == {"enabled": True, "hour": 0, "minute": 0, "real": False}
    scheduler.remove(home=tmp_path)
    assert not path.exists()


# ── the daily run on Windows ─────────────────────────────────────────────────────
def test_windows_script_quotes_spaces_and_appends_to_the_log(tmp_path):
    script = scheduler.build_cmd_script(["C:\\Program Files\\Job Finder\\cli.exe", "--cli", "scan"], tmp_path, tmp_path / "s.log", {"A": "1"})
    lines = script.split("\r\n")
    assert lines[0] == "@echo off" and 'set "A=1"' in lines and f'cd /d "{tmp_path}"' in lines
    assert lines[-2].startswith('"C:\\Program Files\\Job Finder\\cli.exe" --cli scan >> "') and lines[-2].endswith('" 2>&1')


def test_windows_task_scheduler_failures_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_schtasks", lambda *a: done(1, "", "ERROR: Access is denied."))
    out = scheduler.install_windows(9, 0, ["x", "--auto-apply"], tmp_path, tmp_path / "logs" / "s.log")
    assert out == {"ok": False, "error": "ERROR: Access is denied."} and not (tmp_path / "schedule.json").exists()
    monkeypatch.setattr(scheduler, "_schtasks", lambda *a: done(1))
    assert "could not create" in scheduler.install_windows(9, 0, ["x"], tmp_path, tmp_path / "s.log")["error"]
    queries = []
    monkeypatch.setattr(scheduler, "_schtasks", lambda *a: queries.append(a[0]) or done(0))
    assert scheduler.install_windows(7, 0, ["x", "--auto-apply"], tmp_path, tmp_path / "s.log") == {"ok": True}
    assert scheduler.status_windows(tmp_path)["real"] is True
    monkeypatch.setattr(scheduler, "_schtasks", lambda *a: done(1))                           # the task was deleted by hand
    assert scheduler.status_windows(tmp_path) == {"enabled": False}
    (tmp_path / "schedule.json").write_text("{broken")
    assert scheduler.status_windows(tmp_path) == {"enabled": False}
    assert scheduler.remove_windows(tmp_path) == {"ok": True} and not (tmp_path / "run_daily.cmd").exists()


def test_the_public_functions_pick_windows_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    seen = []
    monkeypatch.setattr(scheduler, "_schtasks", lambda *a: seen.append(a[0]) or done(0))
    assert scheduler.install(6, 15, ["x"], tmp_path, tmp_path / "s.log") == {"ok": True}
    assert scheduler.status(workspace=tmp_path)["enabled"] is True
    assert scheduler.remove(workspace=tmp_path) == {"ok": True}
    assert seen == ["/Create", "/Query", "/Delete"]

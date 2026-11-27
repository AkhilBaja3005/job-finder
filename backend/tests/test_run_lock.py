"""One run at a time per workspace, and a clear message when the Excel file is open elsewhere."""
import os
import sys
import subprocess

import pytest

from services import run_lock as rl

MACAPP = os.path.join(os.path.dirname(__file__), "..", "..", "macapp")
sys.path.insert(0, MACAPP)


def test_lock_is_taken_and_released(tmp_path):
    path = str(tmp_path / "data" / "run.lock")
    with rl.run_lock("scan", path):
        assert os.path.isfile(path) and rl.holder(path) is None          # our own pid does not count as "another run"
    assert not os.path.exists(path)


def test_a_live_other_process_blocks_a_second_run(tmp_path):
    path = str(tmp_path / "run.lock")
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        open(path, "w").write(f"{other.pid} scan\n")
        assert rl.holder(path) == other.pid
        with pytest.raises(rl.RunInProgress, match="already going"):
            with rl.run_lock("apply", path):
                pass
        assert os.path.exists(path)                                       # the other run's lock is untouched
    finally:
        other.kill()
        other.wait()


def test_a_lock_left_by_a_dead_process_is_ignored(tmp_path):
    path = str(tmp_path / "run.lock")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    open(path, "w").write(f"{dead.pid} scan\n")
    assert rl.holder(path) is None
    with rl.run_lock("scan", path):
        assert rl.holder_is_me(path)
    for bad in ("", "abc", "0", "-5"):
        open(path, "w").write(bad)
        assert rl.holder(path) is None
    assert rl.holder(str(tmp_path / "missing.lock")) is None and rl.pid_alive(0) is False and rl.pid_alive(os.getpid()) is True


def test_an_unwritable_folder_never_stops_the_run(tmp_path):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the folder should be")
    ran = []
    with rl.run_lock("scan", str(blocker / "run.lock")):
        ran.append(1)
    assert ran == [1]


def test_the_app_refuses_to_start_while_another_run_holds_the_lock(tmp_path, monkeypatch):
    import scan_panel as sp
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "run.lock").write_text(f"{other.pid} apply\n")
        assert sp._other_run_holder(tmp_path) == other.pid
        out = sp.ScanRunner(["x"]).start(["scan"], {}, tmp_path, "scan")
        assert out["ok"] is False and "already going" in out["error"]
    finally:
        other.kill()
        other.wait()
    assert sp._other_run_holder(tmp_path / "nowhere") is None


def test_an_excel_file_open_elsewhere_gives_a_plain_message(monkeypatch):
    import scan_panel as sp
    monkeypatch.setattr(sp, "GATE_ENABLED", False)          # no Google session on a build machine

    class TrackerLockedError(RuntimeError):
        pass

    @sp._guarded
    def locked(self):
        raise TrackerLockedError("Cannot write x.xlsx")

    out = locked(object.__new__(sp.Api))
    assert out["ok"] is False and "open in another program" in out["error"]


def test_cli_exits_when_another_run_holds_the_lock(tmp_path, monkeypatch):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "run.lock").write_text(f"{other.pid} scan\n")
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        res = subprocess.run([sys.executable, "-c", "import sys; sys.argv = ['job-finder', 'prepare']; from job_finder.cli import main; main()"], cwd=root, capture_output=True, text=True, timeout=60,
                             env={**os.environ, "JOB_FINDER_ROOT": str(tmp_path), "PYTHONPATH": root + os.pathsep + os.path.join(root, "backend")})
        assert res.returncode == 3 and "already going" in (res.stdout + res.stderr)
    finally:
        other.kill()
        other.wait()

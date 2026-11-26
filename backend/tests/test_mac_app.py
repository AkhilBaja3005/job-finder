import importlib.util
import os
import socket
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "macapp" / "job_finder_app.py"
spec = importlib.util.spec_from_file_location("job_finder_app", APP)
app = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
sys.modules["job_finder_app"] = app
spec.loader.exec_module(app)  # type: ignore[union-attr]


def test_support_dir_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("JOB_FINDER_APP_HOME", raising=False)
    assert app.support_dir() == Path.home() / "Library" / "Application Support" / "Job Finder"
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path))
    assert app.support_dir() == tmp_path


def test_prepare_environment_creates_private_env_and_sets_root(monkeypatch, tmp_path):
    home = tmp_path / "jf"
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(home))
    monkeypatch.delenv("JOB_FINDER_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    result = app.prepare_environment()
    assert result == home
    assert os.environ["JOB_FINDER_ROOT"] == str(home)
    assert os.environ["HOST"] == "127.0.0.1"
    env_file = home / ".env"
    assert env_file.exists() and (env_file.stat().st_mode & 0o777) == 0o600


def test_prepare_environment_keeps_an_existing_env(monkeypatch, tmp_path):
    home = tmp_path / "jf"
    home.mkdir()
    (home / ".env").write_text("KEEP_ME=1\n")
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    app.prepare_environment()
    assert (home / ".env").read_text() == "KEEP_ME=1\n"


def test_pick_port_free_busy_and_reuse(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        monkeypatch.setattr(app, "_is_job_finder", lambda port: False)
        port, running = app.pick_port(busy)
        assert port != busy and running is False  # something else holds it: take another port
        monkeypatch.setattr(app, "_is_job_finder", lambda port: True)
        assert app.pick_port(busy) == (busy, True)  # our own server is already there: reuse it
    free_port = socket.socket()
    free_port.bind(("127.0.0.1", 0))
    number = free_port.getsockname()[1]
    free_port.close()
    assert app.pick_port(number) == (number, False)

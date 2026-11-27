"""Log lines must reach a pipe as they are printed, not all at the end."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cli_output_is_line_buffered_on_a_pipe():
    code = ("import sys, time; sys.path.insert(0, %r); from job_finder.cli import _line_buffer_output; _line_buffer_output();"
            "print('first'); time.sleep(3); print('second')" % str(ROOT))
    env = {"PATH": "/usr/bin:/bin"}                                       # no PYTHONUNBUFFERED: the case that used to hold lines back
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=env)
    start = time.time()
    assert proc.stdout.readline().strip() == "first" and time.time() - start < 2.5
    proc.wait(timeout=10)


def test_line_buffering_never_raises_on_odd_streams(monkeypatch):
    from job_finder import cli
    monkeypatch.setattr(sys, "stdout", object())
    cli._line_buffer_output()

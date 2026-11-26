"""A daily run through macOS launchd, so the app does not have to be open.

One LaunchAgent in ~/Library/LaunchAgents runs the same command the Run button runs, at a chosen time. It defaults to a
practice run (fills forms, never submits). A real run needs the caller to say so explicitly."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

LABEL = "space.job-finder.daily"


def agent_path(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(hour: int, minute: int, program: List[str], workspace: Path, log_file: Path, env_extra: Optional[Dict[str, str]] = None) -> bytes:
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise ValueError("The time must be between 00:00 and 23:59.")
    env = {"JOB_FINDER_ROOT": str(workspace), "PYTHONUNBUFFERED": "1", **(env_extra or {})}
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(p) for p in program],
        "WorkingDirectory": str(workspace),
        "StartCalendarInterval": {"Hour": int(hour), "Minute": int(minute)},
        "EnvironmentVariables": env,
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
        "RunAtLoad": False,
        "ProcessType": "Background",
    })


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=20)


# ── Windows: Task Scheduler ──────────────────────────────────────────────────────
TASK_NAME = "Job Finder Daily"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, timeout=30)


def build_cmd_script(program: List[str], workspace: Path, log_file: Path, env: Dict[str, str]) -> str:
    """A .cmd file that sets the environment, moves to the folder and runs the command, appending output to the log."""
    lines = ["@echo off"] + [f'set "{k}={v}"' for k, v in env.items()]
    lines += [f'cd /d "{workspace}"', " ".join(f'"{p}"' if " " in p else p for p in program) + f' >> "{log_file}" 2>&1']
    return "\r\n".join(lines) + "\r\n"


def _windows_files(workspace: Path) -> tuple:
    return workspace / "run_daily.cmd", workspace / "schedule.json"


def install_windows(hour: int, minute: int, program: List[str], workspace: Path, log_file: Path, env_extra: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        return {"ok": False, "error": "The time must be between 00:00 and 23:59."}
    script, meta = _windows_files(workspace)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    script.write_text(build_cmd_script(program, workspace, log_file, {"JOB_FINDER_ROOT": str(workspace), "PYTHONUNBUFFERED": "1", **(env_extra or {})}), encoding="utf-8")
    result = _schtasks("/Create", "/TN", TASK_NAME, "/TR", f'"{script}"', "/SC", "DAILY", "/ST", f"{int(hour):02d}:{int(minute):02d}", "/F")
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or result.stdout or "Task Scheduler could not create the task.").strip()[:200]}
    meta.write_text(json.dumps({"hour": int(hour), "minute": int(minute), "real": "--auto-apply" in program}), encoding="utf-8")
    return {"ok": True}


def remove_windows(workspace: Path) -> Dict[str, Any]:
    _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    for f in _windows_files(workspace):
        try:
            f.unlink()
        except OSError:
            pass
    return {"ok": True}


def status_windows(workspace: Path) -> Dict[str, Any]:
    _, meta = _windows_files(workspace)
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"enabled": False}
    if _schtasks("/Query", "/TN", TASK_NAME).returncode != 0:
        return {"enabled": False}
    return {"enabled": True, **data}


def install(hour: int, minute: int, program: List[str], workspace: Path, log_file: Path, env_extra: Optional[Dict[str, str]] = None, home: Optional[Path] = None) -> Dict[str, Any]:
    if sys.platform == "win32":
        return install_windows(hour, minute, program, workspace, log_file, env_extra)
    path = agent_path(home)
    try:
        data = build_plist(hour, minute, program, workspace, log_file, env_extra)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    path.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LABEL}")  # replace an older copy; fails harmlessly when there is none
    result = _launchctl("bootstrap", domain, str(path))
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or "launchctl could not load the schedule.").strip()[:200]}
    return {"ok": True}


def remove(home: Optional[Path] = None, workspace: Optional[Path] = None) -> Dict[str, Any]:
    if sys.platform == "win32":
        return remove_windows(workspace or Path.cwd())
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    path = agent_path(home)
    if path.exists():
        path.unlink()
    return {"ok": True}


def status(home: Optional[Path] = None, workspace: Optional[Path] = None) -> Dict[str, Any]:
    if sys.platform == "win32":
        return status_windows(workspace or Path.cwd())
    path = agent_path(home)
    if not path.exists():
        return {"enabled": False}
    try:
        plist = plistlib.loads(path.read_bytes())
        when = plist.get("StartCalendarInterval") or {}
        args = plist.get("ProgramArguments") or []
        return {"enabled": True, "hour": when.get("Hour", 0), "minute": when.get("Minute", 0), "real": "--auto-apply" in args}
    except Exception:
        return {"enabled": False}

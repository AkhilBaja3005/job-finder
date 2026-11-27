"""Everything that differs between macOS and Windows, in one place: folders, opening files, notifications, Chrome, the
one-window lock. The rest of the app calls these and does not check the platform itself."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
NAME = "mac" if IS_MAC else "windows" if IS_WINDOWS else "linux"


def app_support_dir(app_name: str) -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / app_name
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / app_name
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / app_name


def logs_base(app_name: str) -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / app_name / "Logs"
    if IS_MAC:
        return Path.home() / "Library" / "Logs" / app_name
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / app_name / "logs"


def chrome_candidates() -> List[str]:
    if IS_WINDOWS:
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        return [str(Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe") for r in roots if r]
    if IS_MAC:
        return ["/Applications/Google Chrome.app", str(Path.home() / "Applications" / "Google Chrome.app")]
    return []


def chrome_found() -> bool:
    return any(Path(p).exists() for p in chrome_candidates()) or bool(shutil.which("google-chrome") or shutil.which("chrome"))


def open_command(path: str, as_text: bool = False) -> Optional[List[str]]:
    """The command that opens a file or folder with the system's default program. None when the platform opens it itself."""
    if IS_MAC:
        return ["open", "-t", path] if as_text else ["open", path]
    if IS_WINDOWS:
        return ["notepad.exe", path] if as_text else None
    return ["xdg-open", path]


def open_path(path: str, as_text: bool = False) -> None:
    command = open_command(path, as_text)
    if command:
        subprocess.run(command, check=False)
    elif IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]


def windows_toast_command(title: str, message: str) -> List[str]:
    """PowerShell command that shows a Windows toast. Text goes in as environment-free single-quoted literals."""
    def lit(text: str) -> str:
        return "'" + str(text).replace("'", "''").replace("\r", " ").replace("\n", " ") + "'"
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        "$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        f"$t = $x.GetElementsByTagName('text'); $t.Item(0).AppendChild($x.CreateTextNode({lit(title)})) | Out-Null; "
        f"$t.Item(1).AppendChild($x.CreateTextNode({lit(message)})) | Out-Null; "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Job Finder').Show([Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script]


def notify(title: str, message: str) -> None:
    """A system notification on macOS and Windows; silently nothing elsewhere. It is a nicety, never an error."""
    try:
        if IS_MAC:
            import json
            script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], check=False, timeout=5, capture_output=True)
        elif IS_WINDOWS:
            subprocess.run(windows_toast_command(title, message), check=False, timeout=10, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def lock_file(handle) -> bool:
    """Takes an exclusive lock on an open file. False when another copy of the app already holds it."""
    try:
        if IS_WINDOWS:
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def activate_running_app(app_name: str) -> None:
    if IS_MAC:
        subprocess.run(["osascript", "-e", f'tell application "{app_name}" to activate'], check=False, capture_output=True)

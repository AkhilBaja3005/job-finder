"""One run at a time per workspace: a manual run, a scheduled run and a second window must not fill the same Excel or drive the same Chrome.

The lock is a small file holding the process id. A file left by a process that has died (a crash, a power cut) is ignored."""
import os
import sys
from contextlib import contextmanager
from typing import Iterator, Optional

LOCKED_COMMANDS = ("scan", "apply", "prepare")


class RunInProgress(RuntimeError):
    pass


def lock_path() -> str:
    try:
        from config.constants import resolve_workspace_root
    except ImportError:
        from backend.config.constants import resolve_workspace_root
    return os.path.join(resolve_workspace_root(), "data", "run.lock")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":                       # os.kill(pid, 0) would terminate the process on Windows
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def holder(path: Optional[str] = None) -> Optional[int]:
    """The pid of the live process that holds the lock, or None."""
    path = path or lock_path()
    try:
        pid = int(open(path, encoding="utf-8").read().strip().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid != os.getpid() and pid_alive(pid) else None


@contextmanager
def run_lock(command: str, path: Optional[str] = None) -> Iterator[None]:
    path = path or lock_path()
    other = holder(path)
    if other:
        raise RunInProgress(f"Another Job Finder run is already going (process {other}). Wait for it to finish or stop it, then try again.")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {command}\n")
    except OSError:
        yield                                          # a folder we cannot write to must not stop the run
        return
    try:
        yield
    finally:
        try:
            if holder_is_me(path):
                os.remove(path)
        except OSError:
            pass


def holder_is_me(path: str) -> bool:
    try:
        return int(open(path, encoding="utf-8").read().split()[0]) == os.getpid()
    except (OSError, ValueError, IndexError):
        return False

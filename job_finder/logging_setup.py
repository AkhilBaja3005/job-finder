"""CLI logging: concise on the console, detailed in a rotating log file."""

import logging
import logging.handlers
import os


def log_file_path() -> str:
    base = os.getenv("JOB_FINDER_LOG_DIR") or os.path.expanduser("~/.job-finder/logs")
    return os.path.join(base, "job-finder.log")


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Console shows WARNING by default, DEBUG with --verbose, ERROR with --quiet; the file always keeps DEBUG."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_job_finder", False):
            root.removeHandler(handler)

    console_level = logging.ERROR if quiet else (logging.DEBUG if verbose else logging.WARNING)
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    console._job_finder = True  # type: ignore[attr-defined]
    root.addHandler(console)
    root.setLevel(logging.DEBUG)

    try:
        path = log_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        file_handler._job_finder = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    except OSError:
        pass  # logging to file is best-effort

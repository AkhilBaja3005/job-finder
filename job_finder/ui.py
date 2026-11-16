"""Terminal output helpers for the CLI.

Uses `rich` when it is installed and the output is a terminal, and falls back to plain text
otherwise (pipes, CI, `--no-color`, minimal installs). Global flags are set once via `configure`.
"""

import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:  # rich is a declared dependency but stay usable without it
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:  # pragma: no cover - exercised only on minimal installs
    HAS_RICH = False

_STATE = {"quiet": False, "color": True}
_console: Optional["Console"] = None

STATUS_STYLES = {
    "ok": "green",
    "warn": "yellow",
    "fail": "red",
    "applied": "green",
    "success": "green",
    "ready": "cyan",
    "preview": "cyan",
    "needs review": "yellow",
    "blocked": "yellow",
    "failed": "red",
    "rejected": "red",
}


def configure(quiet: bool = False, no_color: bool = False) -> None:
    """Apply global output flags. NO_COLOR and non-TTY output also disable color."""
    global _console
    _STATE["quiet"] = quiet
    _STATE["color"] = not (no_color or os.getenv("NO_COLOR") or not sys.stdout.isatty())
    _console = None


def is_quiet() -> bool:
    return _STATE["quiet"]


def _get_console() -> Optional["Console"]:
    global _console
    if not HAS_RICH:
        return None
    if _console is None:
        _console = Console(no_color=not _STATE["color"], highlight=False)
    return _console


def _emit(text: str, style: str = "", err: bool = False) -> None:
    console = _get_console()
    if console is not None and not err:
        console.print(text, style=style or None, markup=False)
    else:
        print(text, file=sys.stderr if err else sys.stdout)


def info(message: str) -> None:
    if not _STATE["quiet"]:
        _emit(message)


def success(message: str) -> None:
    if not _STATE["quiet"]:
        _emit(f"[ ok ] {message}", "green")


def warn(message: str) -> None:
    _emit(f"[warn] {message}", "yellow", err=True)


def error(message: str) -> None:
    _emit(f"[error] {message}", "red", err=True)


def status_style(status: str) -> str:
    lowered = (status or "").lower()
    for key, style in STATUS_STYLES.items():
        if key in lowered:
            return style
    return ""


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def print_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[Any]], status_col: Optional[int] = None) -> None:
    """Render a table. Plain aligned text when rich is unavailable."""
    row_list: List[List[str]] = [[str(c) for c in r] for r in rows]
    console = _get_console()
    if console is not None:
        table = Table(title=title, title_justify="left", show_lines=False)
        for col in columns:
            table.add_column(col, overflow="fold")
        for row in row_list:
            if status_col is not None and status_col < len(row):
                style = status_style(row[status_col])
                row = [c if i != status_col or not style else f"[{style}]{c}[/{style}]" for i, c in enumerate(row)]
            table.add_row(*row)
        console.print(table)
        return
    widths = [max(len(str(columns[i])), *(len(r[i]) for r in row_list)) if row_list else len(columns[i]) for i in range(len(columns))]
    print(title)
    print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns)))
    print("  ".join("-" * w for w in widths))
    for row in row_list:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))


def key_values(title: str, pairs: Dict[str, Any]) -> None:
    """Render a small two-column summary."""
    print_table(title, ["Item", "Value"], [[k, v] for k, v in pairs.items()])

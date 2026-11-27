"""
searches.py - one Excel (and one set of application packs) per search.

    applications_tracker/
        scanned_jobs.xlsx, approved_jobs.xlsx           the original single workbook pair = the search called "main"
        searches/
            cyber-security_graduate-3f2a/
                search.json                             what was searched (topics, level, location) + history
                scanned_jobs.xlsx                       everything this search found (the source of truth)
                approved_jobs.xlsx                      the queue `apply` reads for this search
    applications/<search-name>/0007_company_role/       packs for this search's approved jobs

A new topic/level creates a new search; repeating the same search updates the same Excel; `--into NAME` adds results to
any existing one. Every command (`approve`, `prepare`, `review`, `apply`, `open`, `tracker`) works on the CURRENT search
(the one you scanned last, or `--search NAME`). A job applied to in one search is never applied to again from another.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAIN = "main"
APPLIED_STATUSES = ("Applied", "Interview", "Offer", "Rejected")


# ─── locations ────────────────────────────────────────────────────────────────
def _consts():
    try:
        from config import constants as c
    except ImportError:
        from backend.config import constants as c
    return c


def tracker_dir() -> str:
    return _consts().get_applications_tracker_dir()


def searches_root() -> str:
    return os.path.join(tracker_dir(), "searches")


def _workspace() -> str:
    return _consts().resolve_workspace_root()


def _active_file() -> str:
    return os.path.join(_workspace(), "data", "active_search.json")


@dataclass
class Search:
    name: str
    scanned: str
    approved: str
    packs: str
    folder: str
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.scanned)

    @property
    def is_main(self) -> bool:
        return self.name == MAIN


def slug(text: Any, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (s[:limit].strip("-")) or "search"


def auto_name(topics: Iterable[str], level: Optional[str], role: Optional[str] = None) -> str:
    """Deterministic name: same topics + level always give the same search, so repeating it updates the same Excel."""
    topics = [t.strip() for t in topics if t and t.strip()]
    basis = " ".join(topics) if topics else (role or "search")
    digest = hashlib.sha1((basis.lower() + "|" + (level or "any")).encode()).hexdigest()[:4]
    head = slug("-".join(slug(t, 24) for t in topics[:2]) if topics else role, 30)
    return f"{head}-{digest}-{slug(level or 'any', 12)}"          # hyphens only: get_or_create() slugifies names, so they must already be clean


def _paths(name: str) -> Search:
    if name == MAIN:
        td = tracker_dir()
        return Search(MAIN, os.path.join(td, "scanned_jobs.xlsx"), os.path.join(td, "approved_jobs.xlsx"),
                      os.path.join(_workspace(), "applications"), td)
    folder = os.path.join(searches_root(), name)
    return Search(name, os.path.join(folder, "scanned_jobs.xlsx"), os.path.join(folder, "approved_jobs.xlsx"),
                  os.path.join(_workspace(), "applications", name), folder)


def _load_meta(s: Search) -> Dict[str, Any]:
    p = os.path.join(s.folder, "search.json")
    if not s.is_main and os.path.isfile(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_meta(s: Search, **updates: Any) -> None:
    if s.is_main:
        return
    os.makedirs(s.folder, exist_ok=True)
    meta = _load_meta(s)
    meta.update(updates)
    meta["name"] = s.name
    json.dump(meta, open(os.path.join(s.folder, "search.json"), "w", encoding="utf-8"), indent=2, default=str)
    s.meta = meta


def list_searches() -> List[Search]:
    """The original workbook pair (as "main", if it exists) plus every folder under searches/."""
    out: List[Search] = []
    main = _paths(MAIN)
    if main.exists:
        out.append(main)
    root = searches_root()
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            s = _paths(name)
            if s.exists or os.path.isfile(os.path.join(s.folder, "search.json")):   # created, maybe not scanned yet
                s.meta = _load_meta(s)
                out.append(s)
    return out


def get(ref: str) -> Search:
    """A search by name (unique prefix allowed) or by the path of an .xlsx workbook."""
    ref = (ref or "").strip()
    if ref.lower().endswith(".xlsx"):
        path = os.path.abspath(os.path.expanduser(ref))
        folder, fname = os.path.split(path)
        stem = os.path.splitext(fname)[0]
        approved = os.path.join(folder, "approved_jobs.xlsx") if fname == "scanned_jobs.xlsx" else os.path.join(folder, f"{stem}_approved.xlsx")
        return Search(slug(stem, 40), path, approved, os.path.join(_workspace(), "applications", slug(stem, 40)), folder)
    names = {s.name: s for s in list_searches()}
    if ref in names:
        return names[ref]
    hits = [n for n in names if n.startswith(ref) or ref in n]
    if len(hits) == 1:
        return names[hits[0]]
    if not hits:
        raise KeyError(f"No search called '{ref}'. Run `job-finder searches` to see them.")
    raise KeyError(f"'{ref}' matches several searches: {', '.join(hits)}. Be more specific.")


def get_or_create(name: str, **meta: Any) -> Tuple[Search, bool]:
    """(search, created). Creates the folder and search.json for a new name; an existing one is returned untouched."""
    name = slug(name, 60) if name != MAIN else MAIN
    s = _paths(name)
    created = not s.exists
    if created and not s.is_main:
        os.makedirs(s.folder, exist_ok=True)
        save_meta(s, created=datetime.now().isoformat(timespec="seconds"), scans=0, **meta)
    else:
        s.meta = _load_meta(s)
    return s, created


# ─── the current search ───────────────────────────────────────────────────────
def current_name() -> Optional[str]:
    try:
        return json.load(open(_active_file(), encoding="utf-8")).get("name")
    except Exception:
        return None


def set_current(name: str) -> None:
    os.makedirs(os.path.dirname(_active_file()), exist_ok=True)
    json.dump({"name": name}, open(_active_file(), "w", encoding="utf-8"))


def resolve_current(ref: Optional[str] = None) -> Search:
    """`--search REF`, else the current search, else the original workbook pair."""
    if ref:
        return get(ref)
    name = current_name()
    if name:
        try:
            return get(name)
        except KeyError:
            pass
    return _paths(MAIN)


def activate(s: Search) -> None:
    """Point every tracker/pack helper at `s` (environment variables, unless the caller already set them explicitly)."""
    if s.is_main:
        return                                   # the defaults already point at the original pair
    os.environ.setdefault("JOB_FINDER_TRACKER_XLSX", s.scanned)
    os.environ.setdefault("JOB_FINDER_APPLICATIONS_DIR", s.packs)
    if not s.scanned.endswith("scanned_jobs.xlsx"):
        os.environ.setdefault("JOB_FINDER_APPROVED_XLSX", s.approved)


# ─── never apply twice ────────────────────────────────────────────────────────
def handled_elsewhere(exclude_scanned: Optional[str] = None) -> Dict[str, str]:
    """normalized job URL -> name of the search where you already applied (or the job is otherwise finished)."""
    try:
        from .excel_tracker import ExcelTracker, _clean_status, normalize_job_url
    except ImportError:  # pragma: no cover
        from excel_tracker import ExcelTracker, _clean_status, normalize_job_url
    out: Dict[str, str] = {}
    if isinstance(exclude_scanned, (list, tuple, set)):
        skip = {os.path.abspath(x) for x in exclude_scanned}
    else:
        skip = {os.path.abspath(exclude_scanned)} if exclude_scanned else set()
    for s in list_searches():
        if os.path.abspath(s.scanned) in skip:
            continue
        for path in (s.scanned, s.approved):
            if not os.path.isfile(path):
                continue
            for r in ExcelTracker(path).rows():
                if r.get("Job URL") and (str(r.get("Applied") or "No") == "Yes" or _clean_status(r.get("Status")) in APPLIED_STATUSES):
                    out.setdefault(normalize_job_url(r["Job URL"]), s.name)
    return out


def counts(s: Search) -> Dict[str, int]:
    try:
        from .excel_tracker import ExcelTracker
    except ImportError:  # pragma: no cover
        from excel_tracker import ExcelTracker
    rows = ExcelTracker(s.scanned).rows() if s.exists else []
    queue = ExcelTracker(s.approved).rows() if os.path.isfile(s.approved) else []
    return {"jobs": len(rows), "approved": sum(1 for r in queue if str(r.get("Status")) == "Approved"),
            "applied": sum(1 for r in rows if str(r.get("Applied") or "No") == "Yes")}

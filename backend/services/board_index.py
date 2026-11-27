"""
board_index.py - an index of every open London/UK job on thousands of company career boards.

Greenhouse, Lever and Ashby publish each company's open roles through a PUBLIC JSON API (meant for embedding on career
pages). The project ships seed lists of company slugs (~8,300 Greenhouse, ~4,400 Lever, ~3,200 Ashby). This module
visits every board once, keeps only the jobs located in the user's city / UK, and stores them in data/board_index.db.
A scan then searches that index in milliseconds, so it covers thousands of employers instead of the ~80 the live
scanner could handle per run.

    ./jf boards refresh      build / refresh the index (minutes the first time; later runs only re-visit stale boards)
    ./jf boards status       what is in it

Only public endpoints are used (no login, no bot-protection bypass). Requests are rate-limited and identify
themselves. Jobs listed here are CURRENTLY OPEN postings, so the scan's time window is not applied to them.
"""

import asyncio
import json
import os
import re
import sqlite3
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import httpx

SEED_BASE = "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/{ats}_companies.json"
SUPPORTED = ("greenhouse", "lever", "ashby")
ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
USER_AGENT = "job-finder-board-index/1.0 (personal job search; public career-board APIs)"
MAX_BODY = 12_000_000          # bytes; ignore pathological responses
FRESH_HOURS = 20               # a board visited more recently than this is not re-fetched
DEAD_DAYS = 14                 # a board that 404'd is only re-checked after this long
_UK_WORDS = ("united kingdom", "great britain", "england", "uk", "gb")


# ─── paths / database ─────────────────────────────────────────────────────────
def _data_dir() -> str:
    try:
        try:
            from config.constants import resolve_workspace_root
        except ImportError:
            from backend.config.constants import resolve_workspace_root
        root = resolve_workspace_root()
    except Exception:
        root = os.getcwd()
    return os.path.join(root, "data")


def db_path() -> str:
    env = os.getenv("JOB_FINDER_BOARD_DB")
    return os.path.abspath(env) if env else os.path.join(_data_dir(), "board_index.db")


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or db_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    db = sqlite3.connect(p)
    db.execute("""CREATE TABLE IF NOT EXISTS boards (
        ats TEXT NOT NULL, slug TEXT NOT NULL, status TEXT, total_jobs INTEGER DEFAULT 0, local_jobs INTEGER DEFAULT 0,
        checked REAL, PRIMARY KEY (ats, slug))""")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
        ats TEXT NOT NULL, slug TEXT NOT NULL, job_id TEXT NOT NULL, company TEXT, title TEXT, location TEXT, url TEXT,
        posted TEXT, location_pref TEXT, PRIMARY KEY (ats, slug, job_id))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_loc ON jobs(location_pref)")
    return db


# ─── location matching ────────────────────────────────────────────────────────
def location_matches(job_location: str, preferred: str) -> bool:
    """True if a job's location string is in the user's city, or is a UK-wide / UK-remote role.  'London, UK' -> London."""
    loc = (job_location or "").lower()
    if not loc:
        return False
    city = (preferred or "London").split(",")[0].strip().lower()
    if city and re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", loc):
        return True
    uk = any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", loc) for w in _UK_WORDS)
    return uk and bool(re.search(r"remote|anywhere|nationwide|hybrid", loc))


def _pretty(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug.split("|")[0]).strip().title()


# ─── seeds ────────────────────────────────────────────────────────────────────
async def load_seeds(client: httpx.AsyncClient, ats_list: Iterable[str], force: bool = False) -> Dict[str, List[str]]:
    """Company slugs per ATS, cached in data/board_seeds.json for 7 days."""
    cache_file = os.path.join(_data_dir(), "board_seeds.json")
    cache: Dict[str, Any] = {}
    if os.path.exists(cache_file) and not force:
        try:
            cache = json.load(open(cache_file, encoding="utf-8"))
        except Exception:
            cache = {}
    out: Dict[str, List[str]] = {}
    changed = False
    for ats in ats_list:
        entry = cache.get(ats)
        if entry and time.time() - entry.get("fetched", 0) < 7 * 86400:
            out[ats] = entry["slugs"]
            continue
        try:
            r = await client.get(SEED_BASE.format(ats=ats), timeout=30.0)
            slugs = [str(s).strip() for s in r.json() if str(s).strip()] if r.status_code == 200 else []
        except Exception:
            slugs = []
        if slugs:
            cache[ats] = {"fetched": time.time(), "slugs": slugs}
            changed = True
        out[ats] = slugs or (entry["slugs"] if entry else [])
    if changed:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        json.dump(cache, open(cache_file, "w", encoding="utf-8"))
    return out


# ─── fetching one board ───────────────────────────────────────────────────────
def _parse(ats: str, slug: str, data: Any) -> List[Dict[str, Any]]:
    """Normalise a board's API payload to [{id, title, location, url, posted, company}]."""
    out: List[Dict[str, Any]] = []
    if ats == "greenhouse":
        for j in (data.get("jobs") or []) if isinstance(data, dict) else []:
            out.append({"id": j.get("id"), "title": j.get("title"), "location": (j.get("location") or {}).get("name", ""),
                        "url": j.get("absolute_url"), "posted": j.get("first_published") or j.get("updated_at"),
                        "company": j.get("company_name") or _pretty(slug)})
    elif ats == "lever":
        for j in data if isinstance(data, list) else []:
            cat = j.get("categories") or {}
            locs = [cat.get("location") or ""] + list(cat.get("allLocations") or [])
            out.append({"id": j.get("id"), "title": j.get("text"), "location": " | ".join(x for x in dict.fromkeys(locs) if x),
                        "url": j.get("hostedUrl"), "posted": j.get("createdAt"), "company": _pretty(slug)})
    elif ats == "ashby":
        for j in (data.get("jobs") or []) if isinstance(data, dict) else []:
            if j.get("isListed") is False:
                continue
            locs = [j.get("location") or ""] + [s.get("location", "") for s in (j.get("secondaryLocations") or []) if isinstance(s, dict)]
            out.append({"id": j.get("id"), "title": j.get("title"), "location": " | ".join(x for x in locs if x),
                        "url": j.get("jobUrl") or j.get("applyUrl"), "posted": j.get("publishedAt"), "company": _pretty(slug)})
    return [o for o in out if o["id"] and o["title"] and o["url"]]


async def fetch_board(client: httpx.AsyncClient, ats: str, slug: str) -> Tuple[str, List[Dict[str, Any]]]:
    """('ok'|'dead'|'error', jobs). Retries once on rate limiting / server errors."""
    url = ENDPOINTS[ats].format(slug=slug.split("|")[0])
    for attempt in (1, 2):
        try:
            r = await client.get(url, timeout=14.0, follow_redirects=True)
            if r.status_code == 404:
                return "dead", []
            if r.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(1.5 * attempt)
                continue
            if r.status_code != 200 or len(r.content) > MAX_BODY:
                return "error", []
            return "ok", _parse(ats, slug, r.json())
        except Exception:
            await asyncio.sleep(0.5)
    return "error", []


# ─── refresh ──────────────────────────────────────────────────────────────────
async def refresh(ats_list: Optional[Iterable[str]] = None, limit: Optional[int] = None, force: bool = False,
                  concurrency: int = 24, location: str = "London, UK", progress: Optional[Callable[[str], None]] = print,
                  client: Optional[httpx.AsyncClient] = None, path: Optional[str] = None,
                  seeds: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Visit boards and store their jobs in `location` (or UK-remote). Returns a summary dict."""
    ats_list = [a for a in (ats_list or SUPPORTED) if a in SUPPORTED]
    own_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                         limits=httpx.Limits(max_connections=concurrency + 4))
    db = _connect(path)
    started = time.time()
    try:
        seeds = seeds if seeds is not None else await load_seeds(client, ats_list, force=force)
        known = {(a, s): (st, ts) for a, s, st, ts in db.execute("SELECT ats, slug, status, checked FROM boards")}
        todo: List[Tuple[str, str]] = []
        for ats in ats_list:
            for slug in seeds.get(ats, []):
                st, ts = known.get((ats, slug), (None, 0))
                age_h = (time.time() - (ts or 0)) / 3600
                if not force and st in ("ok", "error") and age_h < FRESH_HOURS:
                    continue
                if not force and st == "dead" and age_h < DEAD_DAYS * 24:
                    continue
                todo.append((ats, slug))
        if limit:
            todo = todo[:limit]
        if progress:
            progress(f"[boards] {sum(len(v) for v in seeds.values())} company boards known; visiting {len(todo)} "
                     f"(location: {location}) ...")
        sem = asyncio.Semaphore(concurrency)
        stats = {"visited": 0, "ok": 0, "dead": 0, "error": 0, "jobs_total": 0, "jobs_local": 0}
        pending: List[Tuple[str, str, str, List[Dict[str, Any]]]] = []

        async def one(ats: str, slug: str):
            async with sem:
                status, jobs = await fetch_board(client, ats, slug)
            pending.append((ats, slug, status, jobs))

        async def flush():
            for ats, slug, status, jobs in pending:
                local = [j for j in jobs if location_matches(j["location"], location)]
                db.execute("DELETE FROM jobs WHERE ats=? AND slug=?", (ats, slug))
                db.executemany("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                               [(ats, slug, str(j["id"]), j["company"], j["title"], j["location"], j["url"],
                                 str(j["posted"] or ""), location) for j in local])
                db.execute("INSERT OR REPLACE INTO boards VALUES (?,?,?,?,?,?)", (ats, slug, status, len(jobs), len(local), time.time()))
                stats["visited"] += 1
                stats[status] += 1
                stats["jobs_total"] += len(jobs)
                stats["jobs_local"] += len(local)
            pending.clear()
            db.commit()

        batch = 600
        for i in range(0, len(todo), batch):
            await asyncio.gather(*[one(a, s) for a, s in todo[i:i + batch]])
            await flush()
            if progress:
                progress(f"[boards] {min(i + batch, len(todo))}/{len(todo)} visited  |  {stats['jobs_local']} {location.split(',')[0]} jobs found so far"
                         f"  ({int(time.time() - started)}s)")
        stats["seconds"] = round(time.time() - started, 1)
        return stats
    finally:
        db.close()
        if own_client:
            await client.aclose()


# ─── search / status ──────────────────────────────────────────────────────────
def search(title_filter: Optional[Callable[[str], bool]] = None, location: str = "London, UK",
           path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Jobs in the index for `location` whose title passes `title_filter`. Returns (jobs, stats) where stats counts the
    index size, so a scan can say how much of the market it looked at.
    """
    p = path or db_path()
    if not os.path.exists(p):
        return [], {"boards": 0, "local_jobs": 0, "matched": 0}
    db = _connect(p)
    try:
        boards = db.execute("SELECT COUNT(*) FROM boards WHERE status='ok'").fetchone()[0]
        rows = db.execute("SELECT ats, slug, company, title, location, url, posted FROM jobs WHERE location_pref=?", (location,)).fetchall()
    finally:
        db.close()
    out = []
    for ats, slug, company, title, loc, url, posted in rows:
        if title_filter is not None and not title_filter(title):
            continue
        out.append({"title": title, "company": company, "location": loc, "url": url, "platform": ats.title(),
                    "source": f"{ats.title()} (boards)", "posted_date": posted, "description": "", "estimated": True,
                    "ats_score": 50})
    return out, {"boards": boards, "local_jobs": len(rows), "matched": len(out)}


def status(path: Optional[str] = None) -> Dict[str, Any]:
    p = path or db_path()
    if not os.path.exists(p):
        return {"exists": False, "path": p}
    db = _connect(p)
    try:
        by_ats = {a: {"boards": n, "ok": ok, "jobs": jobs} for a, n, ok, jobs in db.execute(
            "SELECT ats, COUNT(*), SUM(status='ok'), SUM(local_jobs) FROM boards GROUP BY ats")}
        last = db.execute("SELECT MAX(checked) FROM boards").fetchone()[0]
        local = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        db.close()
    return {"exists": True, "path": p, "by_ats": by_ats, "local_jobs": local,
            "age_hours": round((time.time() - last) / 3600, 1) if last else None}

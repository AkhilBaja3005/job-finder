"""
Job Description SQLite cache with 6-hour TTL.

Stores scraped JD results keyed by normalized URL so the same job listing
never gets re-scraped within the TTL window — even across different role
search queries. This is the primary fix for the MCP pipeline's slowness:
the same 10 LinkedIn jobs appear across all 8 role searches; without a
cache they get scraped 8 times each.

Usage (drop-in wrapper around scrape_job_description):
    from services.jd_cache import cached_scrape_job_description
    result = await cached_scrape_job_description(url, browser=browser, on_log=on_log)

Cache location: backend/data/jd_cache.db  (auto-created)
TTL:            6 hours (configurable via JD_CACHE_TTL_SECONDS env var)
"""

import os
import json
import sqlite3
import hashlib
import time
import asyncio
from pathlib import Path
from typing import Optional, Callable

# ── Config ──────────────────────────────────────────────────────────────────
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _BACKEND_ROOT / "data" / "jd_cache.db"
_TTL_SECONDS = int(os.getenv("JD_CACHE_TTL_SECONDS", str(6 * 3600)))  # 6 hours default

# ── Thread-local connection (SQLite isn't thread-safe across threads) ────────
import threading
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Returns a per-thread SQLite connection, creating the DB and table if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads while writing
        conn.execute("PRAGMA synchronous=NORMAL")  # faster writes, still safe
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jd_cache (
                url_hash    TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                scraped_at  REAL NOT NULL,
                result_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_scraped_at ON jd_cache (scraped_at)
        """)
        conn.commit()
        _local.conn = conn
    return _local.conn


def _url_key(url: str) -> str:
    """Normalise URL and hash it — strips tracking params for better dedup."""
    import re
    # Strip common tracking query params
    url = re.sub(r'[?&](utm_[^&]*|refId=[^&]*|trackingId=[^&]*|trk=[^&]*)', '', url)
    url = url.rstrip("?&").strip()
    return hashlib.sha256(url.encode()).hexdigest()


def cache_get(url: str) -> Optional[dict]:
    """Return cached scrape result for url if it exists and is within TTL, else None."""
    try:
        conn = _get_conn()
        key = _url_key(url)
        row = conn.execute(
            "SELECT result_json, scraped_at FROM jd_cache WHERE url_hash = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        age = time.time() - row["scraped_at"]
        if age > _TTL_SECONDS:
            conn.execute("DELETE FROM jd_cache WHERE url_hash = ?", (key,))
            conn.commit()
            return None
        return json.loads(row["result_json"])
    except Exception as e:
        print(f"[jd_cache] get error: {e}")
        return None


def cache_set(url: str, result: dict) -> None:
    """Store scrape result for url in the cache."""
    try:
        conn = _get_conn()
        key = _url_key(url)
        conn.execute(
            """INSERT OR REPLACE INTO jd_cache (url_hash, url, scraped_at, result_json)
               VALUES (?, ?, ?, ?)""",
            (key, url, time.time(), json.dumps(result, default=str))
        )
        conn.commit()
    except Exception as e:
        print(f"[jd_cache] set error: {e}")


def cache_stats() -> dict:
    """Return cache statistics: total entries, hit/miss counts since process start."""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM jd_cache").fetchone()[0]
        fresh = conn.execute(
            "SELECT COUNT(*) FROM jd_cache WHERE scraped_at > ?",
            (time.time() - _TTL_SECONDS,)
        ).fetchone()[0]
        return {"total": total, "fresh": fresh, "stale": total - fresh, "ttl_hours": _TTL_SECONDS / 3600}
    except Exception as e:
        return {"error": str(e)}


def cache_purge_expired() -> int:
    """Delete all expired entries. Returns count of deleted rows."""
    try:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM jd_cache WHERE scraped_at <= ?",
            (time.time() - _TTL_SECONDS,)
        )
        conn.commit()
        return cur.rowcount
    except Exception as e:
        print(f"[jd_cache] purge error: {e}")
        return 0


def cache_clear() -> None:
    """Wipe the entire cache (useful for testing or forced refresh)."""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM jd_cache")
        conn.commit()
    except Exception as e:
        print(f"[jd_cache] clear error: {e}")


# ── Drop-in cached wrapper ───────────────────────────────────────────────────

async def cached_scrape_job_description(
    url: str,
    browser=None,
    on_log: Optional[Callable] = None
) -> dict:
    """
    Drop-in replacement for scrape_job_description() that adds a 6h SQLite cache.

    Cache hit  → returns instantly (no network, no Playwright)
    Cache miss → scrapes normally, stores result, returns it
    """
    # 1. Try cache first
    cached = cache_get(url)
    if cached is not None:
        if on_log:
            on_log(f"[jd_cache] ⚡ Cache hit: {url[:80]}")
        else:
            print(f"[jd_cache] ⚡ Cache hit: {url[:80]}")
        return cached

    # 2. Cache miss — do the real scrape
    from services.scraper import scrape_job_description
    result = await scrape_job_description(url, browser=browser, on_log=on_log)

    # 3. Store in cache (only if we got meaningful content)
    if result and result.get("description") and len(result.get("description", "")) > 100:
        cache_set(url, result)

    return result

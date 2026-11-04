"""
UK Visa Sponsor Registry Service
Downloads, indexes, and searches the official UK Home Office Register of Licensed Sponsors (Workers).
Source: https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers
"""

import os
import re
import csv
import io
import time
import sqlite3
import logging
import urllib.request
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

def _resolve_sponsor_db_path() -> str:
    # 1. HF Spaces persistent storage mount (/data)
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return "/data/uk_sponsors.db"
    # 2. Local fallback
    try:
        from config.constants import resolve_workspace_root
        ws_root = resolve_workspace_root()
    except Exception:
        try:
            from backend.config.constants import resolve_workspace_root
            ws_root = resolve_workspace_root()
        except Exception:
            ws_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(ws_root, "data", "uk_sponsors.db")

DB_PATH = _resolve_sponsor_db_path()
METADATA_TABLE = "uk_sponsors_meta"
SPONSORS_TABLE = "uk_sponsors"

SUFFIXES_PATTERN = re.compile(
    r'\b(ltd|limited|plc|llp|gmbh|inc|incorporated|corp|corporation|group|holdings|services|solutions|uk|international|technologies|technology|consulting)\b',
    re.IGNORECASE
)

def normalize_company_name(name: str) -> str:
    """
    Normalizes company name for robust fuzzy matching:
    - Lowercase
    - Strip punctuation and symbols
    - Strip common legal/corporate suffixes (Ltd, Limited, PLC, Group, etc.)
    - Collapse whitespace
    """
    if not name:
        return ""
    # Lowercase & normalize apostrophes/hyphens
    s = name.lower()
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    # Strip corporate suffixes
    s = SUFFIXES_PATTERN.sub(" ", s)
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {SPONSORS_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    norm_name TEXT NOT NULL,
                    city TEXT,
                    county TEXT,
                    tier_rating TEXT,
                    route TEXT
                )
            """)
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_sponsors_norm_name ON {SPONSORS_TABLE}(norm_name)")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {METADATA_TABLE} (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                )
            """)
    finally:
        conn.close()


def find_latest_govuk_csv_url() -> Optional[str]:
    """Scrapes GOV.UK publication page to find the latest live CSV link."""
    pub_url = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
    try:
        req = urllib.request.Request(pub_url, headers={"User-Agent": "Mozilla/5.0 (JobFinderAI/1.0)"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Match CSV URLs
        csv_matches = re.findall(r'https?://assets\.publishing\.service\.gov\.uk/media/[^\s"\'<>]+\.csv', html)
        if csv_matches:
            return csv_matches[0]
        # Fallback to any publishing CSV
        generic_matches = re.findall(r'https?://[^\s"\'<>]+\.csv', html)
        for m in generic_matches:
            if "worker" in m.lower() or "sponsor" in m.lower():
                return m
    except Exception as e:
        logger.warning(f"[UKSponsorService] Failed to find latest CSV link from gov.uk: {e}")
    return None


def sync_uk_sponsors(force: bool = False) -> Dict[str, Any]:
    """
    Downloads and caches the latest Home Office Register CSV into SQLite.
    Skips if updated within the last 24 hours unless force=True.
    """
    init_db()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT value, updated_at FROM {METADATA_TABLE} WHERE key = 'last_sync'")
        row = cur.fetchone()
        now = time.time()
        if row and not force:
            last_sync_time = float(row["updated_at"])
            # If refreshed within 24 hours (86,400s) and database has records, reuse
            cur.execute(f"SELECT COUNT(*) as cnt FROM {SPONSORS_TABLE}")
            cnt_row = cur.fetchone()
            count = cnt_row["cnt"] if cnt_row else 0
            if count > 0 and (now - last_sync_time) < 86400:
                return {
                    "status": "cached",
                    "total_sponsors": count,
                    "last_updated": row["value"],
                    "age_hours": round((now - last_sync_time) / 3600, 1)
                }

        csv_url = find_latest_govuk_csv_url()
        if not csv_url:
            cur.execute(f"SELECT COUNT(*) as cnt FROM {SPONSORS_TABLE}")
            c = cur.fetchone()["cnt"]
            return {"status": "error", "message": "Could not locate Gov.uk CSV link", "total_sponsors": c}

        logger.info(f"[UKSponsorService] Downloading fresh Home Office CSV from: {csv_url}")
        req = urllib.request.Request(csv_url, headers={"User-Agent": "Mozilla/5.0 (JobFinderAI/1.0)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # Parse CSV
        f = io.StringIO(content)
        reader = csv.reader(f)
        header = next(reader, None)
        
        records = []
        for line in reader:
            if not line or len(line) < 1:
                continue
            name = line[0].strip()
            if not name:
                continue
            norm = normalize_company_name(name)
            city = line[1].strip() if len(line) > 1 else ""
            county = line[2].strip() if len(line) > 2 else ""
            tier = line[3].strip() if len(line) > 3 else ""
            route = line[4].strip() if len(line) > 4 else ""
            records.append((name, norm, city, county, tier, route))

        if records:
            with conn:
                conn.execute(f"DELETE FROM {SPONSORS_TABLE}")
                conn.executemany(
                    f"INSERT INTO {SPONSORS_TABLE} (name, norm_name, city, county, tier_rating, route) VALUES (?, ?, ?, ?, ?, ?)",
                    records
                )
                now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now))
                conn.execute(
                    f"INSERT OR REPLACE INTO {METADATA_TABLE} (key, value, updated_at) VALUES ('last_sync', ?, ?)",
                    (now_str, now)
                )
                conn.execute(
                    f"INSERT OR REPLACE INTO {METADATA_TABLE} (key, value, updated_at) VALUES ('csv_url', ?, ?)",
                    (csv_url, now)
                )

        return {
            "status": "success",
            "total_sponsors": len(records),
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)),
            "csv_url": csv_url
        }
    except Exception as e:
        logger.error(f"[UKSponsorService] Error syncing UK sponsors: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def check_uk_sponsor(company_name: str) -> Dict[str, Any]:
    """
    Checks if a company is currently registered as a licensed sponsor in the Home Office register.
    Performs:
    1. Exact normalized match
    2. Prefix/Sub-string match on normalized tokens
    Returns match dict with verified status and guidance text.
    """
    if not company_name or not company_name.strip():
        return {
            "is_sponsor": False,
            "company_name": company_name,
            "matched_name": None,
            "details": None,
            "message": "No company name provided"
        }

    init_db()
    norm = normalize_company_name(company_name)
    if not norm or len(norm) < 2:
        return {
            "is_sponsor": False,
            "company_name": company_name,
            "matched_name": None,
            "details": None,
            "message": "Company name too short to verify"
        }

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # 1. Exact normalized match
        cur.execute(
            f"SELECT name, norm_name, city, county, tier_rating, route FROM {SPONSORS_TABLE} WHERE norm_name = ? LIMIT 1",
            (norm,)
        )
        row = cur.fetchone()

        # 2. If no exact match and company name has significant length, check if official name starts with exact query as word
        if not row and len(norm) >= 4:
            cur.execute(
                f"SELECT name, norm_name, city, county, tier_rating, route FROM {SPONSORS_TABLE} WHERE norm_name LIKE ? LIMIT 1",
                (f"{norm} %",)
            )
            row = cur.fetchone()

        # 3. If query itself has multiple words (e.g. "Amazon Web Services"), check if query starts with an official sponsor name
        if not row and " " in norm:
            cur.execute(
                f"SELECT name, norm_name, city, county, tier_rating, route FROM {SPONSORS_TABLE} WHERE ? LIKE (norm_name || ' %') ORDER BY length(norm_name) DESC LIMIT 1",
                (norm,)
            )
            row = cur.fetchone()

        if row:
            return {
                "is_sponsor": True,
                "company_name": company_name,
                "matched_name": row["name"],
                "details": {
                    "city": row["city"],
                    "county": row["county"],
                    "tier_rating": row["tier_rating"],
                    "route": row["route"]
                },
                "badge": "✓ UK Visa Sponsor",
                "badge_color": "green",
                "notice": None
            }
        else:
            return {
                "is_sponsor": False,
                "company_name": company_name,
                "matched_name": None,
                "details": None,
                "badge": "✗ Not on sponsor",
                "badge_color": "red",
                "notice": {
                    "title": "Company Could Not Be Found in Sponsor Database",
                    "description": f"{company_name} is not currently registered as a visa sponsor with the UK government.",
                    "advice": "This doesn't necessarily mean they can't sponsor - they may be able to apply for a sponsor license. Consider reaching out directly to ask about their sponsorship policy or future plans."
                }
            }
    finally:
        conn.close()


def get_sponsor_stats() -> Dict[str, Any]:
    """Returns total sponsor count and last synced date."""
    init_db()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) as cnt FROM {SPONSORS_TABLE}")
        cnt = cur.fetchone()["cnt"]
        cur.execute(f"SELECT value FROM {METADATA_TABLE} WHERE key = 'last_sync'")
        row = cur.fetchone()
        last_sync = row["value"] if row else "Never"
        return {
            "total_sponsors": cnt,
            "last_sync": last_sync
        }
    finally:
        conn.close()

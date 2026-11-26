#!/usr/bin/env python3
"""Saves a copy of the Job Finder tables from Supabase to a local file.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=sb_secret_... python scripts/backup_supabase.py [folder]

The file holds personal data (emails, resumes, sync codes), so it is written readable only by you. Keep it somewhere
private and encrypted; never commit it or upload it to a public place such as a GitHub Actions artifact on a public repo.
Needs the secret key, because the tables are locked to the public key.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

TABLES = ("users", "sessions", "user_resumes", "applications")
PAGE = 1000


def fetch_all(base: str, key: str, table: str) -> list:
    rows, start = [], 0
    while True:
        req = urllib.request.Request(
            f"{base}/rest/v1/{table}?select=*&order=id.asc",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items", "Range": f"{start}-{start + PAGE - 1}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            batch = json.load(resp)
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def main() -> int:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or ""
    if not base or not key.startswith("sb_secret_"):
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY (the sb_secret_ key).", file=sys.stderr)
        return 2
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    data, counts = {}, {}
    for table in TABLES:
        try:
            data[table] = fetch_all(base, key, table)
        except Exception as exc:  # a table that does not exist yet should not stop the others
            print(f"  {table}: skipped ({exc})", file=sys.stderr)
            continue
        counts[table] = len(data[table])
    path = out_dir / f"job_finder_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tables": data}, f)
    print(f"Saved {path} ({', '.join(f'{t}: {n}' for t, n in counts.items())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

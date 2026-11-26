#!/usr/bin/env python3
"""Encrypts the API keys users saved before KEY_ENCRYPTION_SECRET was set on the server.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=sb_secret_... KEY_ENCRYPTION_SECRET=... python scripts/reencrypt_saved_keys.py
    ... add --apply to write the changes (the default only reports what it would do)

Run it once, with the same secret the server uses. Keys that are already encrypted are left alone, so running it twice is
safe. Back up first: scripts/backup_supabase.py."""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def request(base: str, key: str, path: str, method: str = "GET", body=None):
    req = urllib.request.Request(
        f"{base}/rest/v1/{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the encrypted keys (default: only report)")
    args = parser.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or ""
    if not base or not key.startswith("sb_secret_") or not (os.environ.get("KEY_ENCRYPTION_SECRET") or os.environ.get("ENCRYPTION_KEY")):
        print("Set SUPABASE_URL, SUPABASE_SERVICE_KEY (sb_secret_...) and KEY_ENCRYPTION_SECRET.", file=sys.stderr)
        return 2
    from services.secret_store import encrypt_secret, is_encrypted
    rows = request(base, key, "users?select=id,gemini_api_key&gemini_api_key=not.is.null") or []
    todo = [r for r in rows if r.get("gemini_api_key") and not is_encrypted(r["gemini_api_key"])]
    print(f"{len(rows)} users have a saved key; {len(todo)} are not encrypted yet.")
    if not args.apply:
        print("Nothing written. Run again with --apply to encrypt them.")
        return 0
    for r in todo:
        request(base, key, f"users?id=eq.{urllib.parse.quote(str(r['id']))}", "PATCH", {"gemini_api_key": encrypt_secret(r["gemini_api_key"])})
    print(f"Encrypted {len(todo)} keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

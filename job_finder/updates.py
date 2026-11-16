"""Update check against PyPI with a 24h local cache."""

import json
import os
import re
import sys


def check_for_updates():
    """
    Non-blocking update check against PyPI / GitHub releases with local cache.
    Caches check result for 24 hours to prevent network overhead on every CLI invocation.
    """
    # Never touch the network or stdout in scripts, pipes, quiet or JSON mode
    if os.getenv("JOB_FINDER_NO_UPDATE_CHECK") or not sys.stdout.isatty() or "--json" in sys.argv or "--quiet" in sys.argv or "-q" in sys.argv:
        return
    try:
        import time
        import urllib.request
        from importlib.metadata import version as get_pkg_version

        from backend.config.constants import APP_VERSION
        current_ver = APP_VERSION
        try:
            current_ver = get_pkg_version("job-finder-ai")
        except Exception:
            pass

        cache_file = os.path.expanduser("~/.config/job-finder/.update_check.json")
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        now = time.time()

        # Read cache
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                latest = cdata.get("latest_version")
                last_check = cdata.get("last_check", 0)
                # If checked within 24h (86400s), reuse cached latest version
                if now - last_check < 86400 and latest:
                    if _parse_ver(latest) > _parse_ver(current_ver):
                        print(f"Update available: v{current_ver} → v{latest}. Run 'pip install --upgrade job-finder-ai' to update.\n", file=sys.stderr)
                    return
            except Exception:
                pass

        # Fetch latest version from PyPI with a strict 1.5s timeout
        req = urllib.request.Request("https://pypi.org/pypi/job-finder-ai/json", headers={"User-Agent": "job-finder-cli"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latest_ver = data.get("info", {}).get("version", current_ver)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"latest_version": latest_ver, "last_check": now}, f)

        if _parse_ver(latest_ver) > _parse_ver(current_ver):
            print(f"Update available: v{current_ver} → v{latest_ver}. Run 'pip install --upgrade job-finder-ai' to update.\n", file=sys.stderr)
    except Exception:
        pass


def _parse_ver(v_str: str):
    """Simple tuple version parser (e.g. '1.2.4' -> (1, 2, 4))."""
    try:
        parts = []
        for x in v_str.strip().lstrip("v").split("."):
            num = re.search(r'\d+', x)
            parts.append(int(num.group()) if num else 0)
        return tuple(parts)
    except Exception:
        return (0, 0, 0)

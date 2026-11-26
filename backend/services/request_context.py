"""Per-request context: the real client IP, and a small limiter for failed sync-code guesses."""
import os
import threading
import time
from contextvars import ContextVar
from typing import Dict, List, Optional

client_ip_var: ContextVar[str] = ContextVar("client_ip", default="unknown")


def get_client_ip(client_host: Optional[str], forwarded_for: Optional[str]) -> str:
    """
    Real client IP behind a reverse proxy. The proxy appends the address it saw to X-Forwarded-For,
    so with TRUSTED_PROXY_COUNT proxies in front (default 1) the client is the Nth entry from the right.
    Earlier entries can be forged by the client and are ignored. Without the header, the socket peer is used.
    """
    try:
        hops = max(0, int(os.getenv("TRUSTED_PROXY_COUNT", "1")))
    except ValueError:
        hops = 1
    if forwarded_for and hops:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return client_host or "unknown"


_MISS_LOCK = threading.Lock()
_MISSES: Dict[str, List[float]] = {}
_MAX_TRACKED_IPS = 5000


def _limits():
    try:
        max_misses = int(os.getenv("SYNC_GUESS_MAX", "10"))
    except ValueError:
        max_misses = 10
    try:
        window = int(os.getenv("SYNC_GUESS_WINDOW_SECONDS", "600"))
    except ValueError:
        window = 600
    return max_misses, window


def sync_guess_blocked(ip: Optional[str] = None) -> bool:
    """True if this IP already made too many failed sync-code lookups in the window."""
    ip = ip or client_ip_var.get()
    max_misses, window = _limits()
    now = time.time()
    with _MISS_LOCK:
        recent = [t for t in _MISSES.get(ip, []) if now - t < window]
        _MISSES[ip] = recent
        return len(recent) >= max_misses


def record_sync_guess_miss(ip: Optional[str] = None) -> None:
    """Counts one failed sync-code lookup for this IP."""
    ip = ip or client_ip_var.get()
    now = time.time()
    with _MISS_LOCK:
        if len(_MISSES) >= _MAX_TRACKED_IPS and ip not in _MISSES:
            _, window = _limits()
            for key in [k for k, v in _MISSES.items() if not v or now - v[-1] >= window]:
                _MISSES.pop(key, None)
            if len(_MISSES) >= _MAX_TRACKED_IPS:
                return
        _MISSES.setdefault(ip, []).append(now)

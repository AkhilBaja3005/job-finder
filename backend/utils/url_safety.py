"""Blocks server-side requests to private, loopback and cloud-metadata addresses (SSRF)."""
import ipaddress
import socket
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Optional, Tuple
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """The URL points somewhere the server must not fetch from."""


_BLOCKED_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),   # carrier-grade NAT
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, includes the cloud metadata address
    ipaddress.ip_network("fd00::/8"),
)
_BLOCKED_NAMES = ("localhost", "metadata.google.internal", "metadata")
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home")


def _ip_is_public(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified):
        return False
    return not any(ip in net for net in _BLOCKED_NETS)


@lru_cache(maxsize=4096)
def _host_is_public(host: str) -> Tuple[bool, str]:
    host = host.strip("[]").lower().rstrip(".")
    if not host:
        return False, "missing host"
    if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
        return False, f"host '{host}' is internal"
    try:
        ipaddress.ip_address(host)
        return (_ip_is_public(host), "private or reserved address") if not _ip_is_public(host) else (True, "")
    except ValueError:
        pass  # a name, resolved below
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False, f"cannot resolve '{host}'"
    for info in infos:
        if not _ip_is_public(str(info[4][0])):
            return False, f"'{host}' resolves to a private or reserved address"
    return True, ""


def is_public_http_url(url: Optional[str]) -> Tuple[bool, str]:
    """(True, "") if the URL is http(s) and every address its host resolves to is public."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False, "invalid URL"
    if parsed.scheme not in ("http", "https"):
        return False, "only http and https URLs are allowed"
    if parsed.username or parsed.password:
        return False, "URLs with credentials are not allowed"
    return _host_is_public(parsed.hostname or "")


def ensure_public_http_url(url: Optional[str]) -> str:
    ok, why = is_public_http_url(url)
    if not ok:
        raise UnsafeURLError(why)
    return (url or "").strip()


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Re-checks every redirect target, so a public URL cannot bounce the server to an internal one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ensure_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req, timeout: Optional[float] = None, context=None):
    """urlopen for URLs a user can choose: checks the URL and each redirect hop first."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    ensure_public_http_url(url)
    handlers: list = [_CheckedRedirects()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout) if timeout is not None else opener.open(req)

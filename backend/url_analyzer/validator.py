"""
backend/url_analyzer/validator.py — URL validation & SSRF protections

Treats every user-provided URL as untrusted input. Responsibilities:

    - URL syntax validation and normalization
    - Dangerous protocol blocking (file://, javascript:, data:, ...)
    - Maximum URL length enforcement
    - Hostname allow-checking (localhost, cloud metadata, internal suffixes)
    - DNS pre-resolution with private/loopback/link-local/metadata IP blocking
      so that no server-side request ever reaches internal infrastructure
    - Safe redirect-target re-validation (bounded redirect depth)

Timeouts and redirect limits are defined here and reused by the whole
package so every network module shares one safety policy.
"""

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

# ──────────────────────────────────────────────
# Safety policy constants
# ──────────────────────────────────────────────

MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 5
DNS_TIMEOUT = 6          # seconds for hostname resolution
REQUEST_TIMEOUT = 10     # seconds for outbound HTTP probes
TLS_TIMEOUT = 8          # seconds for TLS handshake

ALLOWED_SCHEMES = {"http", "https"}

DANGEROUS_SCHEMES = {
    "file", "javascript", "data", "vbscript", "ftp", "gopher",
    "telnet", "ws", "wss", "chrome", "about", "blob", "filesystem",
}

# Hostnames that must never be requested server-side.
BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "metadata.azure.internal",
    "metadata",
}

# Internal / non-routable DNS suffixes.
BLOCKED_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".home.arpa",
    ".invalid", ".example", ".test", ".lan", ".corp",
)

DEFAULT_PORTS = {"http": 80, "https": 443}

_THREAD_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="zyra-url")


# ──────────────────────────────────────────────
# IP-based SSRF guards
# ──────────────────────────────────────────────

def is_blocked_ip(ip_str: str) -> bool:
    """True when the IP may not be contacted by the server (SSRF guard)."""
    try:
        addr = ipaddress.ip_address(str(ip_str).strip("[]"))
    except ValueError:
        return True  # unparsable → treat as blocked

    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) — check the embedded v4.
    if addr.version == 6 and getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped

    if (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
        return True

    # Carrier-grade NAT 100.64.0.0/10 (varies by Python version in is_private)
    if addr.version == 4:
        try:
            if addr in ipaddress.ip_network("100.64.0.0/10"):
                return True
        except ValueError:
            return True
    return False


def resolve_host_ips(hostname: str, timeout: float = DNS_TIMEOUT):
    """
    Resolve a hostname with a hard timeout.

    Returns:
        (True, [ip, ...])        — resolved successfully
        (False, "error message") — resolution failed / timed out
    """
    def _resolve():
        infos = socket.getaddrinfo(hostname, None)
        ips = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        return ips

    try:
        future = _THREAD_POOL.submit(_resolve)
        ips = future.result(timeout=timeout)
        return True, ips
    except socket.gaierror:
        return False, "Domain could not be resolved."
    except Exception as e:
        return False, f"DNS resolution error ({type(e).__name__})."


def hostname_is_blocked(hostname: str) -> bool:
    """True when the hostname itself targets local/internal infrastructure."""
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return True
    if host in BLOCKED_HOSTNAMES:
        return True
    for suffix in BLOCKED_HOST_SUFFIXES:
        if host.endswith(suffix):
            return True
    return False



# ──────────────────────────────────────────────
# URL validation & normalization
# ──────────────────────────────────────────────

def normalize_url(raw_url: str) -> str:
    """Add a default https:// scheme when the user omitted one (matches the
    existing ZYRA link-security convention: 'HTTPS assumed')."""
    raw = (raw_url or "").strip()
    if raw and "://" not in raw:
        return "https://" + raw
    return raw


def validate_url(raw_url: str) -> dict:
    """
    Validate and normalize an untrusted URL string.

    Returns a dict:
        valid           — bool
        error           — human-readable message (when invalid)
        error_code      — INVALID_URL | TOO_LONG | DANGEROUS_PROTOCOL |
                          BLOCKED_TARGET | MISSING_HOST | BAD_PORT
        normalized_url  — full URL with scheme (when valid)
        scheme / hostname / port / path / query / fragment
    """
    raw = (raw_url or "").strip()
    result = {
        "valid": False, "error": None, "error_code": None,
        "normalized_url": None, "scheme": None, "hostname": None,
        "port": None, "path": None, "query": None, "fragment": None,
    }

    if not raw:
        result["error"] = "Please enter a URL to analyze."
        result["error_code"] = "INVALID_URL"
        return result

    if len(raw) > MAX_URL_LENGTH:
        result["error"] = "URL exceeds the maximum allowed length (2048 characters)."
        result["error_code"] = "TOO_LONG"
        return result

    candidate = normalize_url(raw)

    try:
        parsed = urlparse(candidate)
    except ValueError:
        result["error"] = "Please enter a valid URL."
        result["error_code"] = "INVALID_URL"
        return result

    scheme = (parsed.scheme or "").lower()
    if scheme in DANGEROUS_SCHEMES:
        result["error"] = f"Dangerous protocol blocked: '{scheme}:'"
        result["error_code"] = "DANGEROUS_PROTOCOL"
        return result
    if scheme not in ALLOWED_SCHEMES:
        result["error"] = "Please enter a valid URL (http:// or https://)."
        result["error_code"] = "INVALID_URL"
        return result

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        result["error"] = "Please enter a valid URL including a domain name."
        result["error_code"] = "MISSING_HOST"
        return result

    # Spaces/control characters inside the host indicate malformed input.
    if any(ch.isspace() or ord(ch) < 32 for ch in hostname):
        result["error"] = "Please enter a valid URL."
        result["error_code"] = "INVALID_URL"
        return result

    # Port parsing (urlparse raises ValueError on bad ports)
    try:
        port = parsed.port
    except ValueError:
        result["error"] = "Invalid port in URL."
        result["error_code"] = "BAD_PORT"
        return result
    if port is not None and not (1 <= port <= 65535):
        result["error"] = "Invalid port in URL."
        result["error_code"] = "BAD_PORT"
        return result

    # Local / internal hostnames are never requested server-side.
    if hostname_is_blocked(hostname):
        result["error"] = (
            "This target points to a local or internal address and cannot be "
            "analyzed for safety reasons."
        )
        result["error_code"] = "BLOCKED_TARGET"
        return result

    # Pre-resolve and block private / metadata IPs (SSRF guard).
    ok, ips_or_err = resolve_host_ips(hostname)
    if ok:
        for ip in ips_or_err:
            if is_blocked_ip(ip):
                result["error"] = (
                    "This target resolves to a private or internal address "
                    "and cannot be analyzed for safety reasons."
                )
                result["error_code"] = "BLOCKED_TARGET"
                return result

    result.update({
        "valid": True,
        "normalized_url": urlunparse(parsed),
        "scheme": scheme,
        "hostname": hostname,
        "port": port if port is not None else DEFAULT_PORTS.get(scheme),
        "path": parsed.path or "/",
        "query": parsed.query or None,
        "fragment": parsed.fragment or None,
    })
    return result


def check_redirect_target(location: str, depth: int) -> dict:
    """
    Re-validate a redirect Location target under the same SSRF rules.

    Returns {allowed: bool, reason: str|None, url: str|None}.
    """
    if depth >= MAX_REDIRECTS:
        return {"allowed": False, "reason": "Maximum redirect depth exceeded.", "url": None}
    location = (location or "").strip()
    if not location:
        return {"allowed": False, "reason": "Empty redirect target.", "url": None}
    if location.lower().startswith(("javascript:", "data:", "file:", "vbscript:")):
        return {"allowed": False, "reason": "Dangerous redirect protocol.", "url": None}
    return {"allowed": True, "reason": None, "url": location}

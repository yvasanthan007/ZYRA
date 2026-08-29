"""
backend/url_analyzer/dns_analyzer.py — DNS & domain analysis

Resolves the target domain (with SSRF re-checks), splits it into
subdomain / registered-domain parts, and reports hosting-related
information that is technically available with the standard library.

Domain age / WHOIS is only reported when a WHOIS provider is available;
otherwise the field is explicitly marked unavailable (never guessed).
"""

import ipaddress
import os
import re
from urllib.parse import urlparse

from backend.url_analyzer.validator import (
    DNS_TIMEOUT,
    is_blocked_ip,
    resolve_host_ips,
)

# Common multi-part public suffixes handled without an external PSL library.
MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "net.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.in", "net.in", "org.in", "gov.in", "ac.in", "firm.in",
    "com.br", "net.br", "org.br", "gov.br",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
    "com.tr", "net.tr", "org.tr",
    "com.cn", "net.cn", "org.cn", "gov.cn",
    "com.sg", "co.nz", "net.nz", "org.nz",
    "co.za", "com.mx", "co.kr", "com.ar", "com.tw", "co.il",
}

_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", re.IGNORECASE)


def split_domain(hostname: str) -> dict:
    """
    Split a hostname into registered domain + subdomain parts.

    Returns {registered_domain, subdomain_count, subdomains, is_ip_address}.
    """
    host = (hostname or "").strip().lower().rstrip(".")

    # Raw IP host
    try:
        ipaddress.ip_address(host.strip("[]"))
        return {
            "registered_domain": host.strip("[]"),
            "subdomain_count": 0,
            "subdomains": [],
            "is_ip_address": True,
        }
    except ValueError:
        pass

    labels = [l for l in host.split(".") if l]
    if len(labels) < 2:
        return {
            "registered_domain": host,
            "subdomain_count": max(0, len(labels) - 1),
            "subdomains": labels[:-1] if labels else [],
            "is_ip_address": False,
        }

    last_two = ".".join(labels[-2:])
    if last_two in MULTI_PART_SUFFIXES and len(labels) >= 3:
        registered = ".".join(labels[-3:])
    else:
        registered = ".".join(labels[-2:])

    subdomains = labels[: len(labels) - len(registered.split("."))]
    return {
        "registered_domain": registered,
        "subdomain_count": len(subdomains),
        "subdomains": subdomains,
        "is_ip_address": False,
    }


def analyze_dns(url: str, parts: dict) -> dict:
    """
    Resolve the target host and produce the DNS/domain section of a scan.

    Args:
        url    — normalized URL string
        parts  — dict from validator.validate_url() (scheme/hostname/port/...)
    Returns a structured dict for the result payload.
    """
    hostname = parts.get("hostname") or ""
    parsed = urlparse(url)
    dom = split_domain(hostname)

    info = {
        "hostname": hostname,
        "registered_domain": dom["registered_domain"],
        "subdomain_count": dom["subdomain_count"],
        "subdomains": dom["subdomains"],
        "is_ip_address": dom["is_ip_address"],
        "resolved": False,
        "ips": [],
        "ip_address": None,
        "dns_error": None,
        "whois_available": False,
        "domain_age": "Information unavailable",
        "registrar": None,
        "hosting_asn": None,
        "note": None,
    }

    ok, ips_or_err = resolve_host_ips(hostname, timeout=DNS_TIMEOUT)
    if ok:
        public = [ip for ip in ips_or_err if not is_blocked_ip(ip)]
        info["resolved"] = bool(ips_or_err)
        info["ips"] = public or ips_or_err
        info["ip_address"] = (public or ips_or_err)[0] if (public or ips_or_err) else None
        if not info["resolved"]:
            info["dns_error"] = "Domain could not be resolved."
    else:
        info["dns_error"] = ips_or_err

    # WHOIS / domain age: only when a provider is installed/configured.
    try:  # pragma: no cover - optional dependency
        import whois  # noqa: F401
        info["whois_available"] = True
        info["note"] = "WHOIS provider detected but lookup disabled for privacy-safe default."
    except ImportError:
        info["note"] = (
            "WHOIS / domain-age lookup unavailable (no WHOIS provider configured)."
        )

    _ = os, parsed, _HOST_RE  # keep namespace stable for future extensions
    return info

"""
backend/dns_lookup/validator.py — DNS target validation & sanitization

Every user-supplied DNS target (panel input, chat message, voice transcript)
passes through this module before any query is issued.

Protections:
    - strict character allow-list (letters/digits/dot/hyphen only) so shell
      metacharacters can never survive — although the resolver itself never
      touches a shell (dnspython library calls only)
    - length limits (RFC 1035: 253 chars total, 63 per label)
    - scheme/path/port/userinfo stripping ("https://example.com/x:8080")
    - block loopback / private / link-local / reserved IP ranges
    - block internal hostnames (localhost, *.local, *.internal, ...)
"""

import ipaddress
import re
from typing import Dict

MAX_DOMAIN_LENGTH = 253   # RFC 1035 maximum fully-qualified length
MAX_LABEL_LENGTH = 63     # RFC 1035 maximum label length

# A label: starts/ends alphanumeric, hyphens allowed inside, punycode ok.
_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")

# Hostnames / pseudo-domains that must never be queried.
_BLOCKED_NAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "broadcasthost", "dns", "resolver",
}
# TLD-ish suffixes that refer to the local machine / internal networks.
_RESERVED_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".intranet",
    ".lan", ".home", ".host", ".corp", ".test", ".example", ".invalid",
)

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


class DomainValidationError(ValueError):
    """Raised when a requested DNS target fails validation."""


def _strip_input(raw: str) -> str:
    """Reduce arbitrary user input to a bare hostname or IP literal."""
    text = (raw or "").strip().strip("\"'` ")
    # Remove scheme (https://, ftp://, dns:// ...)
    text = _SCHEME_RE.sub("", text)
    # Remove path / query / fragment
    for sep in ("/", "?", "#"):
        text = text.split(sep, 1)[0]
    # Remove userinfo ("user:pass@host") and port ("host:53")
    text = text.rsplit("@", 1)[-1]
    text = text.split(":", 1)[0]
    # Remove 'dns'/'lookup' style prefixes people naturally type
    text = text.strip().strip(".").strip().lower()
    return text


def is_ip_address(text: str) -> bool:
    """True when text is a literal IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _ip_is_queryable(ip_text: str) -> bool:
    """Public, global unicast addresses only — SSRF-style guard."""
    ip = ipaddress.ip_address(ip_text)
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return True


def validate_domain(raw: str) -> Dict:
    """
    Validate and normalize a DNS lookup target.

    Returns a dict:
        {"domain": <str>, "domain_display": <str>, "is_ip": <bool>}

    Raises DomainValidationError with a user-friendly reason otherwise.
    """
    if raw is None or not str(raw).strip():
        raise DomainValidationError("Please enter a domain name.")

    host = _strip_input(str(raw))

    if not host:
        raise DomainValidationError("Please enter a valid domain name.")
    if len(host) > MAX_DOMAIN_LENGTH:
        raise DomainValidationError("Domain is too long (maximum 253 characters).")
    if any(ch in host for ch in " \t\n\r\\/'\"`;$|&<>!*%^~[]{}(),"):
        raise DomainValidationError("Domain contains invalid characters.")

    # ── Bare IP literal (enables reverse / PTR lookup) ──
    if is_ip_address(host):
        if not _ip_is_queryable(host):
            raise DomainValidationError(
                "Private, loopback and reserved IP addresses cannot be looked up."
            )
        return {"domain": host, "domain_display": host, "is_ip": True}

    # ── Hostname path ──
    if " " in host:
        raise DomainValidationError("Domain must not contain spaces.")
    if "." not in host:
        raise DomainValidationError(
            "Enter a fully qualified domain, e.g. example.com"
        )

    labels = host.split(".")
    if len(labels) < 2:
        raise DomainValidationError(
            "Enter a fully qualified domain, e.g. example.com"
        )
    for label in labels:
        if not label:
            raise DomainValidationError("Domain contains an empty label.")
        if len(label) > MAX_LABEL_LENGTH:
            raise DomainValidationError("A domain label exceeds 63 characters.")
        if not _LABEL_RE.match(label):
            raise DomainValidationError(
                f"'{label}' is not a valid domain label."
            )

    # The top-level label must be alphabetic (or punycode for IDN TLDs)
    tld = labels[-1]
    if not re.match(r"^[a-z]{2,63}$", tld) and not tld.startswith("xn--"):
        raise DomainValidationError(f"'{tld}' is not a valid top-level domain.")

    if host in _BLOCKED_NAMES or host.endswith(_RESERVED_SUFFIXES):
        raise DomainValidationError(
            "Internal/local hostnames cannot be looked up."
        )

    return {"domain": host, "domain_display": host, "is_ip": False}

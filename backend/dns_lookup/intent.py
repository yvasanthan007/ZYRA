"""
backend/dns_lookup/intent.py — DNS_LOOKUP intent detection

Detects the DNS_LOOKUP intent in chat / voice text and extracts the target
domain automatically.

Supported commands (chat or voice):
    "Analyze DNS of example.com"
    "DNS lookup for example.com"
    "Check MX records for example.com"
    "Check the DNS records of example.com"
    "What nameservers does example.com use?"
    "Lookup example.com"
    "Resolve google.com"
    "nslookup example.com"
    "Check SPF records for example.com"
    "Reverse DNS for 8.8.8.8"
    ...or a bare domain, which triggers a lookup automatically.
"""

import re
from typing import Optional

from backend.dns_lookup.validator import is_ip_address

# Bare domain / IP extractor: the first token that looks like a hostname.
# Deliberately permissive here — the validator re-checks everything.
_DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})\b\.?",
    re.IGNORECASE,
)
_IP_RE = re.compile(
    r"\b(\d{1,3}(?:\.\d{1,3}){3})\b"
)

# Explicit DNS trigger phrases / keywords. Matching is case-insensitive
# substring based (robust to voice transcription variance).
_DNS_TRIGGERS = [
    "dns", "mx record", "mx records", "nameserver", "name server",
    "name servers", "nameservers", "nslookup", "dig ", "zone record",
    "spf record", "spf records", "dmarc", "dkim", "txt record", "txt records",
    "cname", "soa record", "soa records", "a record", "a records",
    "aaaa", "ptr record", "reverse dns", "reverse lookup", "dnssec",
    "domain lookup", "resolve domain", "resolve the domain",
    "lookup domain", "whois-style", "mail exchanger",
]

# Verbs that commonly start a DNS request
_DNS_VERBS = ["lookup", "look up", "check", "analyze", "analyse", "query",
              "resolve", "find", "get", "show", "scan", "inspect"]


def is_dns_intent(text: str) -> bool:
    """
    True when the message should activate the DNS Lookup feature.

    Rules (strongest first):
      - The word "dns"/"nslookup"/"dnssec" appears with any verb or alone.
      - A record-type keyword (mx, spf, dmarc, cname, nameserver, txt, soa,
        ptr, reverse dns) appears anywhere.
      - "lookup"/"resolve" appears together with a bare domain or IP.
    """
    if not text:
        return False
    t = text.lower().strip()

    has_domain = bool(_DOMAIN_RE.search(t) or _IP_RE.search(t))

    # Strong direct signals
    if "dns" in t or "nslookup" in t or "dnssec" in t or "dmarc" in t:
        return True

    # Record-type keywords
    for kw in ("mx record", "mx records", "nameserver", "name server",
               "spf", "cname", "soa", "ptr", "txt record", "txt records",
               "a record", "a records", "aaaa", "reverse dns",
               "mail exchanger", "mx of", "mx for"):
        if kw in t:
            return True

    # lookup/resolve + a target
    if has_domain and any(v in t for v in ("lookup", "look up", "resolve")):
        return True

    return False


def extract_dns_target(text: str) -> Optional[str]:
    """Extract the first plausible domain or IP from the text, or None."""
    if not text:
        return None
    t = text.strip()

    # A URL with a scheme is an acceptable source of a domain
    url_match = re.search(r"https?://((?:[a-z0-9\-]+\.)+[a-z]{2,63})", t, re.IGNORECASE)
    if url_match:
        return url_match.group(1).rstrip(".")

    ip = _IP_RE.search(t)
    if ip:
        return ip.group(1)

    dom = _DOMAIN_RE.search(t)
    if dom:
        return dom.group(1).lower().rstrip(".")
    return None


def build_chat_ack(target) -> str:
    """
    Chat acknowledgement sent by ZYRA when the DNS_LOOKUP intent fires.
    With a target: activation notice (panel opens + lookup runs).
    Without: a short request for the domain.
    """
    if target:
        return (
            "DNS LOOKUP ACTIVATED\n"
            f"Target: {target}\n"
            "Running real DNS queries: A, AAAA, CNAME, MX, NS, TXT/SPF/DMARC, "
            "SOA, PTR and DNSSEC — then scoring the domain's DNS security."
        )
    return (
        "DNS LOOKUP ACTIVATED. Please provide the domain you'd like me to "
        "look up — for example: \"Analyze DNS of example.com\"."
    )

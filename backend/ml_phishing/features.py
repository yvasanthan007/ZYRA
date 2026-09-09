"""
backend/ml_phishing/features.py — Lexical feature extraction for ZYRA's ML
phishing classifier.

Pure-Python and fully offline: no DNS, no HTTP, no third-party calls. A URL
is converted into a fixed-length numeric feature vector in microseconds, so
the classifier can run as a regular stage of every URL scan.

The same feature list is used at training time (dataset.py → train.py) and
at inference time (predictor.py). If you add a feature here you MUST
retrain the model:  python -m backend.ml_phishing.train
"""

import ipaddress
import math
import re
from urllib.parse import urlparse

# Reuse the curated word lists from the rule engine so the ML layer and the
# heuristic layer share a single source of truth.
from backend.url_analyzer.threat_detector import (
    CREDENTIAL_KEYWORDS,
    IMPERSONATION_TARGETS,
    SUSPICIOUS_TLDS,
    URL_SHORTENERS,
    URGENCY_KEYWORDS,
)

# Compound (second-level) public suffixes for registrable-domain extraction
_COMPOUND_TLDS = (
    "co.uk", "org.uk", "co.in", "co.jp", "co.nz", "co.za", "co.kr",
    "com.au", "com.br", "com.sg", "com.mx", "net.au", "or.jp",
)

# Ordered feature vector consumed by the model. NEVER reorder entries —
# only append new features at the end, then retrain the model.
FEATURE_NAMES = [
    "url_length",
    "hostname_length",
    "num_dots_host",
    "num_hyphens_host",
    "num_digits_host",
    "digit_ratio_host",
    "num_subdomains",
    "max_label_length",
    "domain_entropy",
    "has_ip_host",
    "is_https",
    "has_nonstandard_port",
    "suspicious_tld",
    "is_shortener",
    "has_punycode",
    "has_userinfo_trick",
    "double_slash_in_path",
    "num_percent_encoded",
    "num_special_chars",
    "num_at",
    "path_length",
    "path_depth",
    "query_length",
    "num_query_params",
    "credential_keywords",
    "urgency_keywords",
    "brand_misplaced",
    "has_hex_blob",
]

FEATURE_DESCRIPTIONS = {
    "url_length": "Total URL length",
    "hostname_length": "Hostname length",
    "num_dots_host": "Dot count in the hostname",
    "num_hyphens_host": "Hyphen count in the hostname",
    "num_digits_host": "Digit count in the hostname",
    "digit_ratio_host": "Share of digits in the hostname",
    "num_subdomains": "Subdomain levels below the registrable domain",
    "max_label_length": "Longest hostname label",
    "domain_entropy": "Character entropy of the hostname (randomness)",
    "has_ip_host": "Raw IP address instead of a domain",
    "is_https": "Uses HTTPS",
    "has_nonstandard_port": "Non-standard port in the URL",
    "suspicious_tld": "High-risk top-level domain (.xyz, .tk, ...)",
    "is_shortener": "Known URL shortener",
    "has_punycode": "Punycode ('xn--') homograph host",
    "has_userinfo_trick": "'@' userinfo trick hiding the real host",
    "double_slash_in_path": "'//' inside the path (redirect-style)",
    "num_percent_encoded": "Percent-encoded characters",
    "num_special_chars": "Special characters (= & % $ ! * , ; ~ _ +)",
    "num_at": "'@' symbols in the URL",
    "path_length": "Path length",
    "path_depth": "Path depth (number of '/' segments)",
    "query_length": "Query-string length",
    "num_query_params": "Number of query parameters",
    "credential_keywords": "Credential-bait keywords (login, verify, ...)",
    "urgency_keywords": "Urgency/manipulation keywords (urgent, claim, ...)",
    "brand_misplaced": "Known brand in subdomain/path of another domain",
    "has_hex_blob": "Long hex blob (token-like) in path/query",
}

_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def registered_domain(host: str) -> str:
    """Best-effort registrable (second-level) domain, e.g. 'evil.com'."""
    host = (host or "").lower()
    labels = host.split(".")
    for ctld in _COMPOUND_TLDS:
        if host.endswith("." + ctld) and len(labels) >= 3:
            return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def subdomain_count(host: str) -> int:
    """Subdomain labels below the registrable domain (www excluded)."""
    host = (host or "").lower()
    reg = registered_domain(host)
    if not host or host == reg:
        return 0
    prefix = host[: -(len(reg) + 1)]
    return len([p for p in prefix.split(".") if p and p != "www"])


def shannon_entropy(text: str) -> float:
    """Character entropy of a string — random-looking hosts score higher."""
    if not text:
        return 0.0
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _brand_misplaced(host: str, path: str, reg: str) -> bool:
    """
    True when a known impersonation target appears somewhere it should not:
    in a subdomain of another domain (paypal.com.verify-account.tk) or in a
    credential-bait path of an unrelated domain (/paypal-login.php).
    """
    host_flat = host.replace("-", "").replace(".", "")
    reg_flat = reg.replace("-", "").replace(".", "")
    path_flat = path.lower().replace("-", "")
    for brand in IMPERSONATION_TARGETS:
        if brand in reg_flat:
            continue  # the brand actually owns this domain
        if brand in host_flat:
            return True
        if brand in path_flat and any(k in path_flat for k in CREDENTIAL_KEYWORDS):
            return True
    return False


def _normalize(url: str):
    """urlparse with scheme assumption for bare hosts (no exception escapes)."""
    url = (url or "").strip()
    if url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "http://" + url
    try:
        return urlparse(url)
    except ValueError:
        return urlparse("")


def _is_ip_host(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────
# Feature extraction
# ──────────────────────────────────────────────

def extract_features(url: str) -> dict:
    """
    Compute the full feature vector for a URL. Always returns every feature
    (0/False when not applicable) so the vector shape stays stable even for
    malformed input.
    """
    parsed = _normalize(url)
    raw = (url or "").strip().lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    query = parsed.query or ""
    scheme = (parsed.scheme or "").lower()
    reg = registered_domain(host) if host else ""

    labels = [l for l in host.split(".") if l] if host else []
    digits_host = sum(ch.isdigit() for ch in host)
    special_chars = sum(raw.count(c) for c in "=&%$!*,;~_+")

    try:
        port = parsed.port
    except ValueError:
        port = -1
    nonstandard_port = port is not None and port != _SCHEME_DEFAULT_PORTS.get(scheme)

    credential_hits = sum(1 for k in CREDENTIAL_KEYWORDS if k in raw)
    urgency_hits = sum(1 for k in URGENCY_KEYWORDS if k in raw)

    return {
        "url_length": len(raw),
        "hostname_length": len(host),
        "num_dots_host": host.count("."),
        "num_hyphens_host": host.count("-"),
        "num_digits_host": digits_host,
        "digit_ratio_host": (digits_host / len(host)) if host else 0.0,
        "num_subdomains": subdomain_count(host) if host else 0,
        "max_label_length": max((len(l) for l in labels), default=0),
        "domain_entropy": round(shannon_entropy(host), 4),
        "has_ip_host": int(_is_ip_host(host)),
        "is_https": int(scheme == "https"),
        "has_nonstandard_port": int(bool(nonstandard_port)),
        "suspicious_tld": int(any(
            (host == t or host.endswith("." + t)) for t in SUSPICIOUS_TLDS
        )),
        "is_shortener": int(any(
            (host == s or host.endswith("." + s)) for s in URL_SHORTENERS
        )),
        "has_punycode": int("xn--" in host),
        "has_userinfo_trick": int("@" in (parsed.netloc or "")),
        "double_slash_in_path": int("//" in path),
        "num_percent_encoded": raw.count("%"),
        "num_special_chars": special_chars,
        "num_at": raw.count("@"),
        "path_length": len(path),
        "path_depth": max(0, path.count("/") - 1),
        "query_length": len(query),
        "num_query_params": query.count("="),
        "credential_keywords": min(credential_hits, 6),
        "urgency_keywords": min(urgency_hits, 6),
        "brand_misplaced": int(_brand_misplaced(host, path, reg)) if host else 0,
        "has_hex_blob": int(bool(re.search(r"[0-9a-f]{16,}", path + query))),
    }


def feature_vector(url: str) -> list:
    """Feature dict → ordered numeric list matching FEATURE_NAMES."""
    feats = extract_features(url)
    return [float(feats.get(name, 0)) for name in FEATURE_NAMES]


def describe_feature(name: str) -> str:
    """Human-readable description for a feature name."""
    return FEATURE_DESCRIPTIONS.get(name, name.replace("_", " "))


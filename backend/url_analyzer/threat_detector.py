"""
backend/url_analyzer/threat_detector.py - URL structure threat detection

Heuristic threat-indicator checks performed on the URL itself and on data
collected by the DNS / SSL / redirect analyzers. Checks are adapted from
ZYRA's existing backend/link_security.py engine and extended with new
indicators. Every finding is transparent: severity, category, human
explanation and the exact score impact applied by risk_scorer.
"""

from difflib import SequenceMatcher
from urllib.parse import parse_qsl

SEVERITY_IMPACT = {
    "CRITICAL": 40,
    "HIGH": 22,
    "MEDIUM": 10,
    "LOW": 3,
    "INFO": 0,
}

IMPERSONATION_TARGETS = [
    "paypal", "google", "facebook", "amazon", "apple", "microsoft",
    "netflix", "instagram", "whatsapp", "twitter", "linkedin",
    "dropbox", "icloud", "coinbase", "binance", "steam", "roblox",
    "office365", "outlook", "gmail", "yahoo", "dhl", "fedex", "usps",
]

SUSPICIOUS_TLDS = {
    "xyz", "tk", "ml", "ga", "cf", "gq", "top", "work", "click", "link",
    "zip", "mov", "rest", "fit", "loan", "date", "racing", "download",
    "stream", "icu", "cyou", "cam", "bar", "buzz", "monster", "quest",
}

URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "is.gd", "ow.ly",
    "cutt.ly", "rb.gy", "shorturl.at", "rebrand.ly", "t.ly", "tiny.cc",
    "s.id", "v.gd", "buff.ly", "lnkd.in", "shorte.st", "clk.sh",
}

CREDENTIAL_KEYWORDS = [
    "login", "log-in", "signin", "sign-in", "signon", "password",
    "passwd", "credential", "auth", "authenticate", "account",
    "verify", "verification", "secure", "security", "update",
    "confirm", "banking", "wallet", "invoice", "payment", "billing",
    "unlock", "suspended", "limited", "recovery", "reset",
]

URGENCY_KEYWORDS = [
    "urgent", "immediately", "alert", "warning", "action-required",
    "suspended", "locked", "unusual-activity", "unusual", "expires",
    "final-notice", "limited-time", "act-now", "prize", "winner",
    "gift", "bonus", "free", "claim",
]


def _make_finding(fid, severity, category, title, detail, impact=None, positive=False):
    return {
        "id": fid,
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "score_impact": SEVERITY_IMPACT[severity] if impact is None else impact,
        "positive": positive,
    }


def _host_and_path(parts):
    host = (parts.get("hostname") or "").lower()
    path = (parts.get("path") or "").lower()
    query = parts.get("query") or ""
    return host, path, query


def _registered_domain(host, domain_info):
    if domain_info and domain_info.get("registered_domain"):
        return domain_info["registered_domain"].lower()
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _check_raw_ip(host, parts):
    if not host:
        return None
    import ipaddress
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    return _make_finding(
        "raw_ip_host", "HIGH", "structure",
        "Raw IP address instead of a domain name",
        "The URL uses a raw IP address instead of a domain name - a common "
        "pattern in phishing and malware hosting.",
    )


def _check_https_missing(scheme, host, path):
    if scheme == "https":
        return None
    sensitive = any(k in path or k in host for k in CREDENTIAL_KEYWORDS)
    return _make_finding(
        "no_https",
        "HIGH" if sensitive else "MEDIUM",
        "protocol",
        "Connection is not encrypted (HTTP)",
        "Sensitive pages contacted over plain HTTP expose anything the user "
        "submits to network observers." if sensitive
        else "The URL uses plain HTTP - traffic is not encrypted.",
    )


def _check_punycode(host, domain_info):
    if "xn--" not in host:
        return None
    return _make_finding(
        "punycode", "HIGH", "obfuscation",
        "Punycode / internationalized domain (xn--)",
        "The hostname contains Punycode (xn--), which can visually imitate "
        "well-known domains (homograph attack).",
    )


def _check_typosquatting(host, reg_domain):
    name = reg_domain.split(".")[0]
    if not name or len(name) < 4:
        return None
    for brand in IMPERSONATION_TARGETS:
        if brand == name:
            continue
        ratio = SequenceMatcher(None, brand, name).ratio()
        digit_swap = name.replace("1", "l").replace("0", "o").replace("5", "s")
        if ratio >= 0.85 or digit_swap == brand or (brand in name and brand != name):
            if brand in name and (name.startswith(brand) or name.endswith(brand)) and ratio < 0.5:
                continue
            return _make_finding(
                "typosquatting", "HIGH", "domain",
                f"Possible impersonation of '{brand}'",
                f"Domain '{reg_domain}' closely resembles '{brand}' - a "
                f"classic typosquatting / brand-spoofing pattern.",
            )
    return None


def _check_suspicious_tld(host):
    labels = host.split(".")
    tld = labels[-1] if labels else ""
    if tld in SUSPICIOUS_TLDS:
        return _make_finding(
            "suspicious_tld", "MEDIUM", "domain",
            f"High-risk top-level domain '.{tld}'",
            f"The '.{tld}' TLD is heavily abused in phishing and malware "
            f"campaigns.",
        )
    return None


def _check_excessive_subdomains(host, domain_info):
    count = domain_info.get("subdomain_count", 0) if domain_info else max(0, len(host.split(".")) - 2)
    if count >= 4:
        return _make_finding(
            "excessive_subdomains", "MEDIUM", "structure",
            f"Excessive subdomains ({count})",
            "Long subdomain chains are frequently used to smuggle a trusted "
            "brand name into the URL while the real domain is different.",
        )
    return None


def _check_shortener(host):
    if host in URL_SHORTENERS:
        return _make_finding(
            "url_shortener", "MEDIUM", "obfuscation",
            "URL shortener masks the destination",
            "Shortened links hide the real destination until after the "
            "redirect, which is commonly abused in phishing messages.",
        )
    return None


def _check_userinfo(url, parts):
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.username or parsed.password:
        return _make_finding(
            "userinfo_redirect", "HIGH", "obfuscation",
            "'@' credential trick in URL",
            "The URL contains userinfo before the host - browsers ignore "
            "everything before '@', so the visible domain is not the real one.",
        )
    return None


def _check_encoding_obfuscation(path, query):
    blob = (path or "") + "?" + (query or "")
    encoded = blob.count("%")
    if "%25" in blob.lower():
        return _make_finding(
            "double_encoding", "MEDIUM", "obfuscation",
            "Double-encoded characters in URL",
            "Double percent-encoding (%25..) is used to evade security "
            "filters and hide the real destination.",
        )
    if encoded >= 3:
        return _make_finding(
            "heavy_encoding", "LOW", "obfuscation",
            "Heavy percent-encoding in URL",
            f"URL contains {encoded} encoded characters - obfuscation is "
            f"sometimes used to disguise the payload.",
        )
    return None


def _check_credential_keywords(host, path, reg_domain):
    blob = f"{host} {path}"
    hits = sorted({k for k in CREDENTIAL_KEYWORDS if k in blob})
    if not hits:
        return None
    return _make_finding(
        "credential_keywords", "MEDIUM", "intent",
        "Credential / account-related keywords",
        f"URL contains credential-related keyword(s): {', '.join(hits[:6])}. "
        f"Combined with other indicators this suggests a phishing lure.",
    )


def _check_urgency_keywords(host, path):
    blob = f"{host} {path}"
    hits = sorted({k for k in URGENCY_KEYWORDS if k in blob})
    if not hits:
        return None
    return _make_finding(
        "urgency_keywords", "LOW", "intent",
        "Urgency / manipulation keywords",
        f"URL contains pressure keywords: {', '.join(hits[:6])} - typical "
        f"of social-engineering pages.",
    )


def _check_unusual_port(parts):
    port = parts.get("port")
    scheme = parts.get("scheme")
    if port is None:
        return None
    defaults = {"http": 80, "https": 443}
    if defaults.get(scheme) == port:
        return None
    return _make_finding(
        "unusual_port", "LOW", "structure",
        f"Unusual port ({port})",
        f"The URL targets non-standard port {port} instead of the default "
        f"for {scheme}.",
    )


def _url_length(parts):
    from urllib.parse import urlunparse
    return len(urlunparse((
        parts.get("scheme") or "", "", parts.get("path") or "",
        "", parts.get("query") or "", parts.get("fragment") or "",
    ))) + len(parts.get("hostname") or "") + 8


def _check_url_length(parts):
    length = _url_length(parts)
    if length > 200:
        return _make_finding(
            "long_url", "MEDIUM", "structure",
            f"Unusually long URL ({length} characters)",
            "Very long URLs often hide the real destination among filler "
            "data or tracking parameters.",
        )
    if length > 100:
        return _make_finding(
            "long_url", "LOW", "structure",
            f"Long URL ({length} characters)",
            "Longer-than-usual URLs can be used to obscure the destination.",
        )
    return None


def _check_query_params(query):
    if not query:
        return None
    try:
        params = parse_qsl(query, keep_blank_values=True)
    except ValueError:
        params = []
    if len(params) > 8:
        return _make_finding(
            "many_params", "LOW", "structure",
            f"Large number of query parameters ({len(params)})",
            "Excessive query parameters are sometimes used to bury a "
            "malicious redirect among tracking values.",
        )
    suspicious_values = [v for _, v in params if v.lower().startswith(("http://", "https://"))]
    if suspicious_values:
        return _make_finding(
            "param_redirect", "MEDIUM", "structure",
            "URL embedded inside query parameters",
            "A query parameter contains another URL - a common open-redirect "
            "or cloaking technique.",
        )
    return None


def _check_redirects(redirect_info):
    if not redirect_info:
        return None
    chain = redirect_info.get("chain") or []
    if redirect_info.get("blocked"):
        return _make_finding(
            "unsafe_redirect", "HIGH", "redirect",
            "Unsafe redirect blocked",
            redirect_info.get("block_reason") or "A redirect target was blocked by safety policy.",
        )
    final_domain = (redirect_info.get("final_registered_domain") or "").lower()
    orig_domain = (redirect_info.get("original_registered_domain") or "").lower()
    if final_domain and orig_domain and final_domain != orig_domain:
        return _make_finding(
            "cross_domain_redirect", "HIGH", "redirect",
            "Redirect to a different domain",
            f"The URL redirects from {orig_domain} to {final_domain} - "
            f"suspicious redirect behavior.",
        )
    if len(chain) >= 3:
        return _make_finding(
            "redirect_chain", "MEDIUM", "redirect",
            f"Long redirect chain ({len(chain)} hops)",
            "Multiple redirect hops are used to hide the final destination "
            "from users and security filters.",
        )
    return None


def _check_ssl_problems(ssl_info):
    if not ssl_info:
        return None
    if ssl_info.get("status") == "invalid":
        bits = []
        if ssl_info.get("self_signed"):
            bits.append("self-signed")
        if ssl_info.get("hostname_mismatch"):
            bits.append("hostname mismatch")
        suffix = f" ({', '.join(bits)})" if bits else ""
        return _make_finding(
            "invalid_certificate", "HIGH", "ssl",
            "Invalid SSL/TLS certificate",
            f"The certificate could not be verified{suffix}. Legitimate "
            f"sites keep valid certificates - this is a strong phishing signal.",
        )
    if ssl_info.get("valid") and ssl_info.get("expires_in_days") is not None:
        days = ssl_info["expires_in_days"]
        if days < 0:
            return _make_finding(
                "expired_certificate", "HIGH", "ssl",
                "Expired SSL/TLS certificate",
                "The certificate has already expired.",
            )
        if days <= 14:
            return _make_finding(
                "expiring_certificate", "LOW", "ssl",
                "Certificate expiring soon",
                f"The certificate expires in {days} day(s).",
            )
    return None


def _check_dns_problems(domain_info):
    if not domain_info:
        return None
    if domain_info.get("is_ip_address"):
        return None
    if not domain_info.get("resolved"):
        return _make_finding(
            "dns_failure", "HIGH", "domain",
            "Domain could not be resolved",
            domain_info.get("dns_error") or "DNS resolution failed.",
        )
    return None


def _check_hyphens(host, reg_domain):
    name = reg_domain.split(".")[0]
    if name.count("-") >= 3:
        return _make_finding(
            "hyphenated_domain", "LOW", "domain",
            "Multiple hyphens in domain name",
            "Hyphen-heavy domains are frequently registered to imitate "
            "legitimate brands (e.g. secure-paypal-login).",
        )
    return None


def detect_threats(url, parts, domain_info=None, ssl_info=None,
                   redirect_info=None) -> list:
    """
    Run every structural threat check and return the findings list.
    Findings are ordered by severity (most severe first).
    """
    host, path, query = _host_and_path(parts)
    scheme = (parts.get("scheme") or "").lower()
    reg_domain = _registered_domain(host, domain_info)

    checks = [
        _check_raw_ip(host, parts),
        _check_https_missing(scheme, host, path),
        _check_punycode(host, domain_info),
        _check_typosquatting(host, reg_domain),
        _check_suspicious_tld(host),
        _check_excessive_subdomains(host, domain_info),
        _check_shortener(host),
        _check_userinfo(url, parts),
        _check_encoding_obfuscation(path, query),
        _check_credential_keywords(host, path, reg_domain),
        _check_urgency_keywords(host, path),
        _check_unusual_port(parts),
        _check_url_length(parts),
        _check_query_params(query),
        _check_redirects(redirect_info),
        _check_hyphens(host, reg_domain),
        _check_ssl_problems(ssl_info),
        _check_dns_problems(domain_info),
    ]

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    findings = [c for c in checks if c is not None]
    findings.sort(key=lambda f: (severity_order.get(f["severity"], 9), f["id"]))
    return findings

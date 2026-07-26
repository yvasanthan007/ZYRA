"""
backend/link_security.py — Zyra Backend Security Analysis Module

Role:
    Zyra's backend-only link security analyzer. Its sole job is to inspect and
    analyze links for phishing, malicious intent, or suspicious attributes.

Execution Context:
    - BACKEND ONLY. This module never modifies, alters, renders, or triggers
      updates to the frontend dashboard UI under any circumstances.
    - Activated whenever the user provides a link, or says
      "Analyse the link" / "Analyze this URL" (and variants).

Analysis Checklist:
    1. Domain & Structure
       - Typosquatting / brand spoofing (e.g. paypaI.com, g00gle.com)
       - Excessive subdomains or mismatched / high-risk TLDs
       - Raw IP address instead of a domain name
    2. Protocol & Security
       - http:// instead of https://, escalated on sensitive/login pages
    3. Obfuscation & Redirects
       - URL shorteners (bit.ly, tinyurl, ...) masking the destination
       - Encoded characters (%XX) or '@' symbols used to redirect the browser
       - Punycode homograph hosts (xn--)
    4. Context & Intent
       - Urgency / manipulation keywords (verify-account, urgent-action,
         update-billing, suspended, confirm-identity, ...)

Output (structured, text-only — exact format):
    Verdict: [SAFE | SUSPICIOUS | PHISHING DETECTED]
    Risk Score: [Low | Medium | High | Critical]

    Key Observations:
    • <domain / protocol state>
    • <suspicious patterns / typos>
    ...

    Recommendation:
    <1-sentence actionable advice>

Optional Backend Tool Hook (function-calling style):
    If the VIRUSTOTAL_API_KEY environment variable is set, a silent VirusTotal
    lookup is performed in the backend and merged into the report. No API key
    is required for the heuristic engine.
"""

import os
import re
import socket
from urllib.parse import urlparse, unquote


# ──────────────────────────────────────────────
# Persona / System Instruction Block
# (inject into Zyra's system instructions so she treats link analysis as a
#  backend-only text task — see brain.py)
# ──────────────────────────────────────────────

SECURITY_ANALYST_PERSONA = (
    "SECURITY ANALYSIS MODE: You are Zyra's Backend Security Analysis Module. "
    "Whenever the user provides a link or says 'Analyse the link' / 'Analyze this URL', "
    "the inspection is performed silently by Zyra's backend security engine and its "
    "structured, text-only report (Verdict / Risk Score / Key Observations / "
    "Recommendation) is returned directly to the user. Never fabricate, simulate, or "
    "alter that report yourself, and never modify, render, or trigger updates to the "
    "frontend dashboard UI for link analysis."
)


# ──────────────────────────────────────────────
# Trigger Detection & URL Extraction
# ──────────────────────────────────────────────

TRIGGER_PHRASES = (
    "analyse the link", "analyze the link",
    "analyse this link", "analyze this link",
    "analyse the url", "analyze the url",
    "analyse this url", "analyze this url",
    "check this link", "check the link",
    "check this url", "check the url",
    "scan this link", "scan the link",
    "is this link safe", "is this url safe",
    "link analysis", "analyse link", "analyze link",
)

_URL_RE = re.compile(
    r"(https?://[^\s<>\"'\)]+|www\.[^\s<>\"'\)]+|"
    r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)*\.(?:"
    r"com|net|org|io|co|in|uk|us|de|dev|app|ai|me|info|biz|online|site|store|"
    r"live|tv|cc|pw|xyz|top|tk|ml|ga|cf|gq|click|link|win|bid|loan|work|date|ly"
    r")(?:/[^\s<>\"'\)]*)?)",
    re.IGNORECASE,
)


def is_link_analysis_request(text):
    """
    Return True when the user's message should activate the backend link
    security module: either it names a trigger phrase, or it contains a URL
    (a user-provided link).
    """
    if not text:
        return False
    lowered = text.lower()
    if any(phrase in lowered for phrase in TRIGGER_PHRASES):
        return True
    return extract_url(text) is not None


def extract_url(text):
    """
    Extract the first URL (http(s)://, www.*, or bare domain.tld[/path])
    from free-form user text. Returns None when no link is present.
    """
    if not text:
        return None
    match = _URL_RE.search(text)
    if not match:
        return None
    url = match.group(0).rstrip(".,;:!?)]}\"'")
    return url or None


# ──────────────────────────────────────────────
# Threat Intelligence Lists
# ──────────────────────────────────────────────

# High-risk TLDs frequently abused in phishing / malware campaigns
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".gq", ".ml", ".cf", ".tk", ".click", ".download",
    ".review", ".work", ".date", ".men", ".loan", ".win", ".bid",
    ".trade", ".webcam", ".science", ".party", ".racing", ".accountant",
    ".stream", ".gdn", ".mom", ".xin", ".vip", ".pw", ".cc", ".icu",
    ".cam", ".rest", ".monster", ".quest", ".bond", ".cfd", ".sbs",
}

# URL shorteners — mask the final destination
URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "tiny.cc", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "shorturl.at", "t.co", "cli.gs", "migre.me", "ff.im",
    "tiny.pl", "tr.im", "v.gd", "snipurl.com", "short.to", "2.gp",
    "x.co", "budurl.com", "shorte.st", "adf.ly", "bc.vc", "cutt.ly",
    "rb.gy", "bl.ink", "short.link", "rebrand.ly", "t2m.io", "soo.gd",
}

# Urgency / manipulation keywords (context & intent lures)
URGENCY_KEYWORDS = (
    "verify-account", "verify", "urgent-action", "urgent", "update-billing",
    "billing", "suspended", "suspend", "locked", "lockout", "unusual-activity",
    "unusual", "confirm-identity", "confirm", "expire", "expired", "expiring",
    "immediately", "immediate", "action-required", "security-alert",
    "reset-password", "recover", "recovery", "limited", "restriction",
    "restricted", "validate", "reactivate", "invoice", "refund", "claim",
    "winner", "prize", "free-gift", "alert", "warning", "update",
    "verify-now", "login-now", "signin-now", "account-update", "overdue",
)

# Sensitive-path keywords — page types that must never be plain HTTP
SENSITIVE_KEYWORDS = (
    "login", "log-in", "signin", "sign-in", "password", "passwd", "account",
    "billing", "payment", "checkout", "banking", "bank", "credential",
    "card", "credit", "debit", "otp", "2fa", "mfa", "wallet", "ssn",
    "verify", "authenticate", "auth",
)

# Popular brands watched for typosquatting / spoofing
POPULAR_BRANDS = {
    "google": "Google", "facebook": "Facebook", "youtube": "YouTube",
    "twitter": "Twitter", "instagram": "Instagram", "linkedin": "LinkedIn",
    "whatsapp": "WhatsApp", "amazon": "Amazon", "apple": "Apple",
    "microsoft": "Microsoft", "netflix": "Netflix", "paypal": "PayPal",
    "github": "GitHub", "reddit": "Reddit", "gmail": "Gmail",
    "outlook": "Outlook", "yahoo": "Yahoo", "dropbox": "Dropbox",
    "spotify": "Spotify", "telegram": "Telegram", "tiktok": "TikTok",
    "snapchat": "Snapchat", "pinterest": "Pinterest", "ebay": "eBay",
    "wikipedia": "Wikipedia", "zoom": "Zoom", "adobe": "Adobe",
    "wordpress": "WordPress", "shopify": "Shopify", "chase": "Chase",
    "wellsfargo": "Wells Fargo", "binance": "Binance", "coinbase": "Coinbase",
    "steam": "Steam", "discord": "Discord", "openai": "OpenAI",
}

# Compound (second-level) public suffixes for registrable-domain extraction
_COMPOUND_TLDS = (
    "co.uk", "org.uk", "co.in", "co.jp", "co.nz", "co.za", "co.kr",
    "com.au", "com.br", "com.sg", "com.mx", "net.au", "or.jp",
)

# Leet-speak + visual confusable normalization for typosquat detection
_LEET_MAP = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a",
                           "5": "s", "7": "t", "8": "b", "@": "a",
                           "$": "s", "!": "i", "|": "l"})
_VISUAL_MAP = (("rn", "m"), ("vv", "w"), ("cl", "d"))


# ──────────────────────────────────────────────
# Internal Helpers
# ──────────────────────────────────────────────

def _is_ip_host(hostname):
    """True when the host is a raw IPv4/IPv6 address instead of a domain."""
    try:
        socket.inet_pton(socket.AF_INET, hostname)
        return True
    except (socket.error, OSError, ValueError):
        pass
    try:
        socket.inet_pton(socket.AF_INET6, hostname.strip("[]"))
        return True
    except (socket.error, OSError, ValueError):
        return False


def _strip_www(hostname):
    host = hostname.lower()
    return host[4:] if host.startswith("www.") else host


def _registrable_domain(hostname):
    """Best-effort registrable (second-level) domain, e.g. 'evil.com'."""
    host = _strip_www(hostname)
    labels = host.split(".")
    for ctld in _COMPOUND_TLDS:
        if host.endswith("." + ctld) and len(labels) >= 3:
            return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _count_subdomains(hostname):
    """Count subdomains beneath the registrable domain (excluding www)."""
    host = _strip_www(hostname)
    reg = _registrable_domain(host)
    if host == reg:
        return 0
    suffix = "." + reg
    if host.endswith(suffix):
        sub = host[: -len(suffix)]
        return len([p for p in sub.split(".") if p])
    return 0


def _levenshtein(s1, s2):
    """Classic Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1,
                            prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def _normalize_confusables(label):
    """Normalize leet-speak digits and visual confusables in a domain label."""
    normalized = label.translate(_LEET_MAP)
    for fake, real in _VISUAL_MAP:
        normalized = normalized.replace(fake, real)
    return normalized


def _check_typosquatting(hostname):
    """
    Detect typosquatting of a popular brand in the second-level domain label.
    Catches: paypaI.com (capital i), g00gle.com (zeros), payparn.com (rn→m),
    gooogle.com (extra letter), facbook.com (missing letter).

    Returns (brand_name, brand_key) or (None, None).
    """
    sld = _registrable_domain(hostname).split(".")[0]
    if len(sld) < 4:
        return None, None
    normalized = _normalize_confusables(sld)

    for brand_key, brand_name in POPULAR_BRANDS.items():
        if sld == brand_key:
            continue  # exact match is legitimate
        max_dist = 2 if len(brand_key) >= 8 else 1
        raw_dist = _levenshtein(sld, brand_key)
        norm_dist = _levenshtein(normalized, brand_key)
        # norm_dist == 0 with a different raw label = pure look-alike spoof
        if 1 <= raw_dist <= max_dist or (normalized != sld and norm_dist <= max_dist):
            return brand_name, brand_key
    return None, None


def _check_brand_spoof(hostname):
    """
    Detect a brand name embedded in the hostname while the registered domain
    belongs to someone else, e.g. paypal.secure-login.xyz or google.com.evil.com.
    """
    host = _strip_www(hostname)
    sld = _registrable_domain(host).split(".")[0]
    for brand_key, brand_name in POPULAR_BRANDS.items():
        if brand_key in host and sld != brand_key:
            return brand_name, brand_key
    return None, None


def _encoded_char_findings(url, parsed):
    """Detect percent-encoding / double-encoding obfuscation."""
    findings = []
    score = 0
    encoded = re.findall(r"%[0-9a-fA-F]{2}", url)
    if parsed.netloc and re.search(r"%[0-9a-fA-F]{2}", parsed.netloc):
        findings.append(
            "Encoded characters inside the domain name — legitimate domains "
            "never need percent-encoding."
        )
        score += 2
    if "%25" in url.lower():
        findings.append(
            "Double-encoded characters (%25) detected — a common obfuscation trick."
        )
        score += 1
    elif len(encoded) >= 3:
        findings.append(
            f"Heavy use of encoded characters ({len(encoded)} sequences) — "
            "possible URL obfuscation."
        )
        score += 1
    return findings, score


# ──────────────────────────────────────────────
# Optional Backend Tool: VirusTotal (silent)
# ──────────────────────────────────────────────

def _virustotal_check(url):
    """
    Silent backend tool call to VirusTotal (function-calling style hook).
    Only runs when VIRUSTOTAL_API_KEY is set in the environment.
    Returns a details string, or None when unavailable/failed.
    """
    api_key = os.environ.get("VIRUSTOTAL_API_KEY")
    if not api_key:
        return None
    try:
        import requests
        headers = {"x-apikey": api_key}
        submit = requests.post(
            "https://www.virustotal.com/api/v3/urls",
            headers=headers, data={"url": url}, timeout=10,
        )
        if submit.status_code != 200:
            return None
        analysis_id = submit.json().get("data", {}).get("id", "")
        if not analysis_id:
            return None
        result = requests.get(
            f"https://www.virustotal.com/api/v3/analyses/{analysis_id}",
            headers=headers, timeout=10,
        )
        if result.status_code != 200:
            return None
        stats = (result.json().get("data", {}).get("attributes", {})
                 .get("stats", {}))
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        total = stats.get("total", 0)
        if malicious > 0:
            return f"MALICIOUS:{malicious}/{total}"
        if suspicious > 0:
            return f"SUSPICIOUS:{suspicious}/{total}"
        if total > 0:
            return f"CLEAN:{total}"
    except Exception:
        return None
    return None


# ──────────────────────────────────────────────
# Core Analysis Engine
# ──────────────────────────────────────────────

def analyze_url_security(url):
    """
    Run the full backend security checklist on a URL.

    Returns a dict:
        {
            "url": str, "host": str, "scheme": str,
            "verdict": "SAFE" | "SUSPICIOUS" | "PHISHING DETECTED",
            "risk_score": "Low" | "Medium" | "High" | "Critical",
            "risk_points": int,
            "observations": [str, ...],
            "recommendation": str,
        }
    """
    original_url = (url or "").strip()
    scheme_assumed = False
    if original_url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", original_url):
        original_url = "https://" + original_url  # assume TLS when scheme omitted
        scheme_assumed = True

    parsed = urlparse(original_url)
    hostname = parsed.hostname or ""

    # ── Structurally invalid → cannot trust ──
    if not parsed.netloc or not hostname:
        return {
            "url": url, "host": "", "scheme": "",
            "verdict": "SUSPICIOUS", "risk_score": "Medium", "risk_points": 3,
            "observations": [
                "The link is not structurally valid — no readable domain could be parsed.",
                "Malformed links are frequently used to hide the real destination.",
            ],
            "recommendation": (
                "Do not click — a malformed or unreadable link is a common "
                "obfuscation attempt."
            ),
        }

    scheme = parsed.scheme.lower()
    host_display = hostname.lower()
    path_query = (parsed.path or "") + (("?" + parsed.query) if parsed.query else "")
    lower_full = original_url.lower()
    lower_path = path_query.lower()

    risk = 0
    findings = []          # suspicious-pattern bullets (in severity order)
    domain_notes = []      # folded into the first (domain/protocol) bullet

    # ── 1a. Raw IP address instead of domain ──
    ip_host = _is_ip_host(host_display)
    if ip_host:
        risk += 4
        findings.append(
            "Uses a raw IP address instead of a registered domain name — "
            "legitimate services do not host login pages on bare IPs."
        )

    # ── 1b. Typosquatting / brand spoofing ──
    typo_brand, typo_key = (None, None)
    if not ip_host:
        typo_brand, typo_key = _check_typosquatting(host_display)
    if typo_brand:
        risk += 5
        findings.append(
            f"Possible typosquatting: '{_registrable_domain(host_display)}' imitates "
            f"{typo_brand} ({typo_key}.com) — a classic credential-theft pattern."
        )

    spoof_brand, spoof_key = (None, None)
    if not ip_host and not typo_brand:
        spoof_brand, spoof_key = _check_brand_spoof(host_display)
    if spoof_brand:
        risk += 4
        findings.append(
            f"Brand spoofing: '{spoof_key}' appears inside the hostname but the "
            f"registered domain is '{_registrable_domain(host_display)}', not {spoof_brand}."
        )

    # ── 1c. Suspicious / mismatched TLD ──
    matched_tld = next((t for t in SUSPICIOUS_TLDS if host_display.endswith(t)), None)
    if matched_tld:
        risk += 3
        findings.append(
            f"High-risk top-level domain '{matched_tld}' — heavily abused in "
            "phishing and malware campaigns."
        )

    # ── 1d. Excessive subdomains ──
    sub_count = _count_subdomains(host_display)
    if sub_count >= 3:
        risk += 2
        findings.append(
            f"Excessive subdomains ({sub_count} levels) — used to visually bury "
            "the real destination domain."
        )

    # ── 1e. Punycode homograph host ──
    if "xn--" in host_display:
        risk += 3
        findings.append(
            "Punycode host ('xn--') detected — possible internationalized-domain "
            "homograph attack imitating another site."
        )

    # ── 2. Protocol & Security ──
    http_sensitive = False
    if scheme == "http":
        risk += 1
        sensitive_hits = [kw for kw in SENSITIVE_KEYWORDS if kw in lower_path]
        if sensitive_hits:
            http_sensitive = True
            risk += 2
            findings.append(
                f"Insecure HTTP on a sensitive page ({', '.join(sensitive_hits[:3])}) — "
                "credentials would be transmitted unencrypted."
            )
        else:
            findings.append(
                "Uses plain http:// instead of https:// — traffic is not encrypted."
            )

    # ── 3a. URL shortener masking destination ──
    shortener = next((s for s in URL_SHORTENERS
                      if host_display == s or host_display.endswith("." + s)), None)
    if shortener:
        risk += 2
        domain_notes.append(f"it is a {shortener} short link that masks the final destination")
        findings.append(
            f"URL shortener '{shortener}' — the real destination is hidden and "
            "cannot be verified before clicking."
        )

    # ── 3b. '@' redirect trick ──
    if "@" in parsed.netloc:
        risk += 4
        findings.append(
            f"Contains an '@' symbol — the browser ignores everything before it, so "
            f"the real destination is '{host_display}', not what the link appears to show."
        )

    # ── 3c. Encoded-character obfuscation ──
    enc_findings, enc_score = _encoded_char_findings(original_url, parsed)
    risk += enc_score
    findings.extend(enc_findings)

    # ── 4. Context & Intent: urgency keywords ──
    urgency_hits = []
    for kw in URGENCY_KEYWORDS:
        if kw in lower_full and kw not in urgency_hits:
            urgency_hits.append(kw)
    if urgency_hits:
        risk += min(len(urgency_hits), 3)
        findings.append(
            "Urgency / manipulation keywords in the URL: "
            + ", ".join(urgency_hits[:3])
            + " — designed to pressure you into acting without thinking."
        )

    # ── Extra: very long path (obfuscation) ──
    if len(path_query) > 100:
        risk += 1
        findings.append(
            f"Unusually long URL path ({len(path_query)} chars) — may conceal "
            "malicious parameters or redirects."
        )

    # ── Optional silent backend tool: VirusTotal ──
    vt = _virustotal_check(original_url)
    if vt:
        verdict_tag, _, detail = vt.partition(":")
        if verdict_tag == "MALICIOUS":
            risk = max(risk, 8)
            findings.append(
                f"VirusTotal backend scan: flagged MALICIOUS by {detail} security vendors."
            )
        elif verdict_tag == "SUSPICIOUS":
            risk += 2
            findings.append(
                f"VirusTotal backend scan: flagged suspicious by {detail} security vendors."
            )
        else:
            domain_notes.append(f"VirusTotal backend scan clean ({detail} vendors)")

    # ── Verdict & risk mapping ──
    if risk >= 8:
        verdict, risk_score = "PHISHING DETECTED", "Critical"
    elif risk >= 5:
        verdict, risk_score = "PHISHING DETECTED", "High"
    elif risk >= 3:
        verdict, risk_score = "SUSPICIOUS", "Medium"
    elif risk >= 1:
        verdict, risk_score = "SUSPICIOUS", "Low"
    else:
        verdict, risk_score = "SAFE", "Low"

    # ── First bullet: domain / protocol state ──
    if scheme == "https":
        proto_txt = "HTTPS (encrypted)"
    elif scheme == "http":
        proto_txt = "unencrypted HTTP"
    else:
        proto_txt = f"scheme '{scheme or 'unknown'}'"
    host_kind = "raw IP host" if ip_host else "domain"
    domain_bullet = f"{host_kind.capitalize()} '{host_display or 'unknown'}' contacted over {proto_txt}"
    if scheme_assumed:
        domain_bullet += " (scheme not specified — HTTPS assumed)"
    if domain_notes:
        domain_bullet += "; " + "; ".join(domain_notes)
    domain_bullet += "."

    observations = [domain_bullet] + findings
    if not findings:
        observations.append(
            "No typosquatting, spoofing, obfuscation, shorteners, or urgency-lure "
            "patterns detected."
        )

    # ── Recommendation (1 sentence, actionable) ──
    if verdict == "SAFE":
        recommendation = "Safe to visit — no suspicious indicators were detected."
    elif verdict == "SUSPICIOUS":
        recommendation = (
            "Proceed with caution — verify the sender and destination before "
            "clicking or entering any personal information."
        )
    else:
        recommendation = (
            "Do not click or enter credentials — close the page and report the "
            "source of this link."
        )

    return {
        "url": url,
        "host": host_display,
        "scheme": scheme,
        "verdict": verdict,
        "risk_score": risk_score,
        "risk_points": risk,
        "observations": observations,
        "recommendation": recommendation,
    }


# ──────────────────────────────────────────────
# Structured Text-Only Report
# ──────────────────────────────────────────────

def format_security_report(result):
    """
    Render the analysis dict into the exact structured, text-only format:

        Verdict: [SAFE | SUSPICIOUS | PHISHING DETECTED]
        Risk Score: [Low | Medium | High | Critical]

        Key Observations:
        • ...
        • ...

        Recommendation:
        ...
    """
    lines = [
        f"Verdict: {result['verdict']}",
        f"Risk Score: {result['risk_score']}",
        "",
        "Key Observations:",
    ]
    lines.extend(f"• {obs}" for obs in result["observations"])
    lines.extend([
        "",
        "Recommendation:",
        result["recommendation"],
    ])
    return "\n".join(lines)


def analyze_link_request(text):
    """
    Main backend entry point: takes the user's raw message, extracts the link,
    runs the security checklist, and returns the structured text-only report.
    When no link is present, returns a short request for one.
    """
    url = extract_url(text)
    if not url:
        return (
            "Please provide the link you'd like me to analyze — for example: "
            "\"Analyse the link http://example.com/login\"."
        )
    return format_security_report(analyze_url_security(url))


def summarize_for_voice(result):
    """Short voice-friendly summary of an analysis dict (for main.py TTS)."""
    verdict = result.get("verdict", "SUSPICIOUS")
    risk = str(result.get("risk_score", "")).lower()
    if verdict == "SAFE":
        return "I analyzed the link. It appears to be safe."
    if verdict == "SUSPICIOUS":
        return (
            f"Caution. The link looks suspicious with {risk} risk. "
            "Please check the detailed report before opening it."
        )
    return (
        f"Warning! Phishing detected with {risk} risk. "
        "Do not click or enter any credentials."
    )


# ──────────────────────────────────────────────
# Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        "https://www.google.com",
        "https://www.amazon.com/dp/B08N5WRWNW",
        "https://bit.ly/3xM7abc",
        "http://192.168.1.1/login",
        "http://paypa1.com/login",
        "https://g00gle.com",
        "https://payparn.com/verify-account",
        "https://paypal.secure-login.xyz/update-billing",
        "http://trusted.com@evil.com/signin",
        "https://accounts.google.com.evil.tk/urgent-action?u=%25%32%31",
        "Analyse the link https://www.facbook.com/reset-password",
    ]
    for sample in samples:
        print("=" * 64)
        print(f"INPUT: {sample}")
        print("-" * 64)
        print(analyze_link_request(sample))
        print()

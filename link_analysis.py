"""
link_analysis.py — Zyra Link Analysis Module

Provides:
  - URL retrieval from screen OCR or clipboard
  - 8-check heuristic security analysis pipeline
  - Optional VirusTotal API integration
  - Structured analysis results with exact voice response text

Analysis Checks (8-point heuristic):
  1. Suspicious TLD (.xyz, .tk, .ml, etc.)
  2. IP-based host (raw IPv4 address)
  3. Missing HTTPS protocol
  4. URL shortener domains (bit.ly, tinyurl, etc.)
  5. Suspicious keywords in path (login, verify, secure, etc.)
  6. Excessive subdomains (>= 3 levels)
  7. Long URL path (> 100 chars - obfuscation)
  8. Typosquatting detection (Levenshtein distance)

Verdict Mapping:
  - Score 0-1: Safe
  - Score 2-4: Suspicious
  - Score 5+: Dangerous
  - VirusTotal malicious flag overrides to Dangerous
"""

import os
import re
import socket
from urllib.parse import urlparse

import requests

from screen_ocr import get_active_url


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# Set this to your VirusTotal API key to enable API-based threat scanning.
# Leave as None to use heuristic-only analysis.
VIRUSTOTAL_API_KEY = os.environ.get("VIRUSTOTAL_API_KEY", None)


# ──────────────────────────────────────────────
# Threat Intelligence Lists
# ──────────────────────────────────────────────

# Known suspicious / high-risk TLDs often used in phishing/malware
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".gq", ".ml", ".cf", ".tk", ".click", ".download",
    ".review", ".work", ".date", ".men", ".loan", ".win", ".bid",
    ".trade", ".webcam", ".science", ".party", ".racing", ".accountant",
    ".stream", ".gdn", ".mom", ".xin", ".vip", ".pw", ".cc", ".icu",
    ".cam", ".rest", ".monster", ".quest", ".bond", ".cfd", ".sbs",
}

# Known URL shortener domains (can obscure the real destination)
URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "tiny.cc", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "shorturl.at", "t.co", "cli.gs", "yfrog.com", "migre.me",
    "ff.im", "tiny.pl", "tr.im", "v.gd", "snipurl.com", "short.to",
    "2.gp", "x.co", "budurl.com", "shorte.st", "adf.ly", "bc.vc",
    "cutt.ly", "rb.gy", "bl.ink", "short.link", "rebrand.ly", "t2m.io",
}

# Suspicious keywords commonly found in phishing URLs
SUSPICIOUS_KEYWORDS = [
    "login", "signin", "verify", "secure", "account", "update",
    "confirm", "banking", "password", "credential", "authenticate",
    "reset", "recover", "alert", "security", "paypal", "ebay",
    "appleid", "icloud", "dropbox", "amazon", "netflix", "chase",
    "wellsfargo", "bankofamerica", "refund", "invoice", "payment",
    "wallet", "transaction", "suspended", "unusual", "activity",
]

# Popular domains to check for typosquatting
POPULAR_DOMAINS = {
    "google": "Google", "facebook": "Facebook", "youtube": "YouTube",
    "twitter": "Twitter", "instagram": "Instagram", "linkedin": "LinkedIn",
    "whatsapp": "WhatsApp", "amazon": "Amazon", "apple": "Apple",
    "microsoft": "Microsoft", "netflix": "Netflix", "paypal": "PayPal",
    "github": "GitHub", "stackoverflow": "Stack Overflow", "reddit": "Reddit",
    "gmail": "Gmail", "outlook": "Outlook", "yahoo": "Yahoo",
    "dropbox": "Dropbox", "spotify": "Spotify", "telegram": "Telegram",
    "tiktok": "TikTok", "snapchat": "Snapchat", "pinterest": "Pinterest",
    "ebay": "eBay", "wikipedia": "Wikipedia", "zoom": "Zoom",
    "adobe": "Adobe", "wordpress": "WordPress", "shopify": "Shopify",
}


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────

def _is_ip_host(hostname):
    """Check if the hostname is a raw IPv4 address."""
    try:
        socket.inet_pton(socket.AF_INET, hostname)
        return True
    except (socket.error, OSError):
        return False


def _count_subdomains(hostname):
    """Count subdomains in a hostname (excluding www)."""
    parts = hostname.split(".")
    if parts[0] == "www":
        parts = parts[1:]
    return max(0, len(parts) - 2)


def _levenshtein_distance(s1, s2):
    """Compute the Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _check_typosquatting(hostname):
    """
    Check if the hostname is a typosquatting attempt on a popular domain.

    Returns:
        tuple: (is_typo: bool, brand_name: str, original_domain: str)
    """
    hostname_lower = hostname.lower()
    
    # Remove www. prefix for checking
    if hostname_lower.startswith("www."):
        check_name = hostname_lower[4:]
    else:
        check_name = hostname_lower

    # Extract the main domain part (before first dot)
    main_part = check_name.split(".")[0] if "." in check_name else check_name

    for brand_key, brand_name in POPULAR_DOMAINS.items():
        # Exact match is NOT typosquatting
        if main_part == brand_key:
            continue

        # Use Levenshtein distance for fuzzy matching
        # Threshold: distance <= 1 for short names, <= 2 for longer names
        max_distance = 2 if len(brand_key) >= 8 else 1
        distance = _levenshtein_distance(main_part, brand_key)

        if 1 <= distance <= max_distance:
            return True, brand_name, f"{brand_key}.com"

        # Also check with common character substitutions (leet-speak)
        substitutions = {"0": "o", "1": "l", "3": "e", "4": "a",
                         "5": "s", "7": "t", "8": "b"}
        normalized = "".join(substitutions.get(c, c) for c in main_part)
        if normalized != main_part:
            norm_distance = _levenshtein_distance(normalized, brand_key)
            if 1 <= norm_distance <= max_distance:
                return True, brand_name, f"{brand_key}.com"

    return False, None, None


# ──────────────────────────────────────────────
# 8-Check Heuristic Analysis Pipeline
# ──────────────────────────────────────────────

def analyze_url(url: str) -> dict:
    """
    Run the 8-check heuristic security analysis pipeline on a URL.

    Args:
        url: The URL string to analyze.

    Returns:
        dict: Structured analysis result containing:
            - url: target URL string
            - score: total risk points (0+)
            - verdict: "Safe", "Suspicious", or "Dangerous"
            - speech_text: exact string for Zyra to speak/display
            - checks: list of dicts with individual check results
    """
    if not url:
        return {
            "url": url,
            "score": 0,
            "verdict": "Safe",
            "speech_text": "I couldn't find any URL on your screen or in your clipboard.",
            "checks": []
        }

    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    
    checks = []
    total_score = 0

    # ── Check 1: Suspicious TLD ──
    tld_found = None
    for tld in SUSPICIOUS_TLDS:
        if hostname.endswith(tld):
            tld_found = tld
            break
    
    if tld_found:
        total_score += 3
        checks.append({
            "check": "Suspicious TLD",
            "score": 3,
            "details": f"Domain uses high-risk TLD: {tld_found}"
        })

    # ── Check 2: IP-based host ──
    if _is_ip_host(hostname):
        total_score += 3
        checks.append({
            "check": "IP-based Host",
            "score": 3,
            "details": "URL uses raw IP address instead of domain name"
        })

    # ── Check 3: Missing HTTPS ──
    if parsed.scheme != "https":
        total_score += 1
        checks.append({
            "check": "Missing HTTPS",
            "score": 1,
            "details": "Connection not using secure HTTPS protocol"
        })

    # ── Check 4: URL shortener ──
    shortener_found = None
    for shortener in URL_SHORTENERS:
        if shortener in hostname:
            shortener_found = shortener
            break
    
    if shortener_found:
        total_score += 2
        checks.append({
            "check": "URL Shortener",
            "score": 2,
            "details": f"URL shortened by {shortener_found} - destination hidden"
        })

    # ── Check 5: Suspicious keywords ──
    lower_path = path.lower()
    found_keywords = [kw for kw in SUSPICIOUS_KEYWORDS if kw in lower_path]
    if found_keywords:
        keyword_score = min(len(found_keywords), 3)
        total_score += keyword_score
        checks.append({
            "check": "Suspicious Keywords",
            "score": keyword_score,
            "details": f"Contains: {', '.join(found_keywords[:3])}"
        })

    # ── Check 6: Excessive subdomains ──
    subdomain_count = _count_subdomains(hostname)
    if subdomain_count >= 3:
        total_score += 2
        checks.append({
            "check": "Excessive Subdomains",
            "score": 2,
            "details": f"Found {subdomain_count} subdomain levels"
        })

    # ── Check 7: Long path length ──
    if len(path) > 100:
        total_score += 1
        checks.append({
            "check": "Long Path",
            "score": 1,
            "details": f"URL path is {len(path)} characters (potential obfuscation)"
        })

    # ── Check 8: Typosquatting ──
    is_typo, brand_name, original_domain = _check_typosquatting(hostname)
    if is_typo:
        total_score += 3
        checks.append({
            "check": "Typosquatting",
            "score": 3,
            "details": f"Impersonates {brand_name} (expected {original_domain})"
        })

    # ── Determine verdict based on score ──
    if total_score >= 5:
        verdict = "Dangerous"
    elif total_score >= 2:
        verdict = "Suspicious"
    else:
        verdict = "Safe"

    # ── Generate exact speech text per requirements ──
    speech_text = _generate_speech_text(url, verdict, total_score)

    # ── VirusTotal override (if enabled and malicious) ──
    if VIRUSTOTAL_API_KEY:
        vt_verdict = _check_virustotal(url)
        if vt_verdict == "malicious":
            verdict = "Dangerous"
            speech_text = f"Warning! VirusTotal flagged {url} as malicious."
            checks.append({
                "check": "VirusTotal",
                "score": 5,
                "details": "Flagged as malicious by VirusTotal"
            })

    return {
        "url": url,
        "score": total_score,
        "verdict": verdict,
        "speech_text": speech_text,
        "checks": checks
    }


def _generate_speech_text(url: str, verdict: str, score: int) -> str:
    """
    Generate the exact voice response text based on verdict category.
    
    Args:
        url: The analyzed URL
        verdict: "Safe", "Suspicious", or "Dangerous"
        score: Total risk score
        
    Returns:
        str: Exact speech text for Zyra to speak
    """
    if verdict == "Safe":
        return f"I've analyzed the link: {url}. It appears to be safe."
    elif verdict == "Suspicious":
        return f"Caution. The link {url} from your screen appears suspicious."
    else:  # Dangerous
        return f"Warning! The link {url} from your screen appears unsafe."


def _check_virustotal(url: str) -> str:
    """
    Check URL against VirusTotal API (silent background check).
    
    Args:
        url: URL to check
        
    Returns:
        str: "malicious", "suspicious", "safe", or "error"
    """
    if not VIRUSTOTAL_API_KEY:
        return "safe"
    
    try:
        headers = {"x-apikey": VIRUSTOTAL_API_KEY}
        
        # Submit URL for analysis
        submit_url = "https://www.virustotal.com/api/v3/urls"
        response = requests.post(
            submit_url,
            headers=headers,
            data={"url": url},
            timeout=15,
        )
        
        if response.status_code != 200:
            return "safe"
        
        result = response.json()
        analysis_id = result.get("data", {}).get("id", "")
        
        if not analysis_id:
            return "safe"
        
        # Get analysis results
        analysis_url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
        analysis_response = requests.get(
            analysis_url,
            headers=headers,
            timeout=15,
        )
        
        if analysis_response.status_code != 200:
            return "safe"
        
        analysis_result = analysis_response.json()
        stats = analysis_result.get("data", {}).get("attributes", {}).get("stats", {})
        
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        
        if malicious > 0:
            return "malicious"
        elif suspicious > 0:
            return "suspicious"
        else:
            return "safe"
    
    except Exception:
        return "safe"


# ──────────────────────────────────────────────
# Main Analysis Function
# ──────────────────────────────────────────────

def analyze_link() -> dict:
    """
    Complete link analysis pipeline:
    1. Get URL from screen OCR or clipboard
    2. Run 8-check heuristic analysis
    3. Check VirusTotal (if API key configured)
    4. Return structured result with speech text

    Returns:
        dict: Analysis result with url, score, verdict, and speech_text
    """
    # Step 1: Get URL from screen or clipboard
    url = get_active_url()
    
    if not url:
        return {
            "url": None,
            "score": 0,
            "verdict": "Not Found",
            "speech_text": "I couldn't find any URL on your screen or in your clipboard.",
            "checks": []
        }
    
    # Step 2: Run heuristic analysis
    result = analyze_url(url)
    
    return result


# ──────────────────────────────────────────────
# Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Zyra Link Analysis — Standalone Test")
    print("=" * 60)
    print()

    test_urls = [
        "https://www.google.com",
        "http://192.168.1.1/login",
        "https://bit.ly/3xM7abc",
        "https://safe-site.example.com/path/to/page",
        "https://login-verify-secure.xyz/update/account/password",
        "https://www.amazon.com/dp/B08N5WRWNW",
        "http://suspicious-login-page.tk/secure/verify?email=test@example.com",
        "https://www.gooogle.com",           # Typosquatting: google
        "https://www.paypa1.com/login",      # Typosquatting: paypal
        "https://facbook.com/reset",         # Typosquatting: facebook
    ]

    for url in test_urls:
        result = analyze_url(url)
        verdict_icon = {"Safe": "✅", "Suspicious": "⚠️", "Dangerous": "🚫"}.get(result["verdict"], "❓")
        
        print(f"{verdict_icon} {result['verdict']:12s} | Score: {result['score']:2d} | {url}")
        print(f"   🗣️  {result['speech_text']}")
        
        if result["checks"]:
            print(f"   📊 Checks triggered:")
            for check in result["checks"]:
                print(f"      • {check['check']}: {check['details']}")
        print()

    print("=" * 60)
    print("Now testing get_active_url() (OCR + clipboard)...")
    print("(Make sure a URL is visible on screen or in clipboard)")
    print("=" * 60)

    url = get_active_url()
    if url:
        print(f"\n✅ Retrieved URL: {url}")
        result = analyze_url(url)
        print(f"   Verdict: {result['verdict']}")
        print(f"   Speech: {result['speech_text']}")
    else:
        print("\nℹ️  No URL found on screen or clipboard.")
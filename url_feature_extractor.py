"""
url_feature_extractor.py — Pure Lexical URL Feature Extractor for Zyra ML Module

Extracts ~20 static numerical features from a URL string WITHOUT any network calls.
All features are computed offline to guarantee zero network latency.

Features extracted:
  1. url_length - Total URL character count
  2. hostname_length - Hostname character count
  3. path_length - Path + query string length
  4. dot_count - Number of dots in URL
  5. hyphen_count - Number of hyphens in URL
  6. at_count - Number of @ symbols
  7. question_mark_count - Number of ? symbols
  8. equals_count - Number of = symbols
  9. percent_count - Number of % symbols
  10. underscore_count - Number of _ symbols
  11. double_slash_count - Number of // occurrences
  12. has_ip_host - Binary: 1 if hostname is IP address, 0 otherwise
  13. has_url_shortener - Binary: 1 if domain is known URL shortener
  14. has_suspicious_tld - Binary: 1 if TLD is suspicious
  15. digit_ratio_domain - Ratio of digits to letters in domain
  16. digit_ratio_url - Ratio of digits to letters in full URL
  17. subdomain_count - Number of subdomains (excluding www)
  18. typosquatting_distance - Minimum Levenshtein distance to popular brands
  19. phishing_keyword_count - Count of suspicious keywords in URL
  20. path_token_count - Number of path segments
"""

import re
import socket
from urllib.parse import urlparse
import numpy as np


# ──────────────────────────────────────────────
# Configuration Constants
# ──────────────────────────────────────────────

SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".gq", ".ml", ".cf", ".tk", ".click", ".download",
    ".review", ".work", ".date", ".men", ".loan", ".win", ".bid",
    ".trade", ".webcam", ".science", ".party", ".racing", ".accountant",
    ".stream", ".gdn", ".mom", ".xin", ".vip", ".pw", ".cc",
}

URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "tiny.cc", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "shorturl.at", "t.co", "cli.gs", "yfrog.com", "migre.me",
    "ff.im", "tiny.pl", "tr.im", "v.gd", "snipurl.com", "short.to",
    "2.gp", "x.co", "budurl.com", "shorte.st", "adf.ly", "bc.vc",
    "cutt.ly", "rb.gy", "bl.ink", "short.link",
}

SUSPICIOUS_KEYWORDS = [
    "login", "signin", "verify", "secure", "account", "update",
    "confirm", "banking", "password", "credential", "authenticate",
    "reset", "recover", "alert", "security", "paypal", "ebay",
    "appleid", "icloud", "dropbox", "amazon", "netflix", "chase",
    "wellsfargo", "bankofamerica", "refund", "invoice", "payment",
    "wallet", "transaction", "suspended", "unusual", "activity",
]

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

def _is_ip_address(hostname):
    """Check if hostname is a valid IPv4 address."""
    try:
        socket.inet_pton(socket.AF_INET, hostname)
        return True
    except (socket.error, OSError):
        return False


def _count_subdomains(hostname):
    """Count subdomains excluding 'www' prefix."""
    parts = hostname.split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]
    return max(0, len(parts) - 2)


def _levenshtein_distance(s1, s2):
    """Compute Levenshtein edit distance between two strings."""
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


def _get_min_typosquatting_distance(hostname):
    """
    Calculate minimum Levenshtein distance to any popular brand domain.
    Returns 0 if no close match found (distance > 2).
    """
    hostname_lower = hostname.lower()
    
    # Remove www. prefix
    if hostname_lower.startswith("www."):
        check_name = hostname_lower[4:]
    else:
        check_name = hostname_lower
    
    # Extract main domain part (before first dot)
    main_part = check_name.split(".")[0] if "." in check_name else check_name
    
    min_distance = 0
    
    for brand_key in POPULAR_DOMAINS.keys():
        if main_part == brand_key:
            continue  # Exact match is not typosquatting
        
        # Threshold: distance <= 2 for longer names, <= 1 for short names
        max_distance = 2 if len(brand_key) >= 8 else 1
        distance = _levenshtein_distance(main_part, brand_key)
        
        if 1 <= distance <= max_distance:
            # Check with leet-speak substitutions
            substitutions = {"0": "o", "1": "l", "3": "e", "4": "a",
                           "5": "s", "7": "t", "8": "b"}
            normalized = "".join(substitutions.get(c, c) for c in main_part)
            if normalized != main_part:
                norm_distance = _levenshtein_distance(normalized, brand_key)
                distance = min(distance, norm_distance)
            
            if min_distance == 0 or distance < min_distance:
                min_distance = distance
    
    return min_distance


def _count_digits(text):
    """Count digit characters in text."""
    return sum(c.isdigit() for c in text)


def _count_letters(text):
    """Count letter characters in text."""
    return sum(c.isalpha() for c in text)


# ──────────────────────────────────────────────
# Main Feature Extraction Function
# ──────────────────────────────────────────────

def extract_url_features(url):
    """
    Extract numerical features from a URL string.
    
    Args:
        url: Raw URL string (e.g., "https://example.com/path?query=value")
    
    Returns:
        numpy.ndarray: Array of 20 numerical features in fixed order
    """
    if not url or not isinstance(url, str):
        # Return zero vector for invalid input
        return np.zeros(20, dtype=np.float32)
    
    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return np.zeros(20, dtype=np.float32)
    
    hostname = parsed.hostname or ""
    path = parsed.path or ""
    query = parsed.query or ""
    full_path = path + ("?" + query if query else "")
    url_lower = url.lower()
    
    # ── Basic length features ──
    url_length = len(url)
    hostname_length = len(hostname)
    path_length = len(full_path)
    
    # ── Character count features ──
    dot_count = url.count(".")
    hyphen_count = url.count("-")
    at_count = url.count("@")
    question_mark_count = url.count("?")
    equals_count = url.count("=")
    percent_count = url.count("%")
    underscore_count = url.count("_")
    double_slash_count = url.count("//")
    
    # ── Binary features ──
    has_ip_host = 1 if _is_ip_address(hostname) else 0
    
    # Check for URL shortener (check both hostname and full URL)
    has_url_shortener = 0
    for shortener in URL_SHORTENERS:
        if shortener in hostname or shortener in url_lower:
            has_url_shortener = 1
            break
    
    # Check for suspicious TLD
    has_suspicious_tld = 0
    for tld in SUSPICIOUS_TLDS:
        if hostname.endswith(tld):
            has_suspicious_tld = 1
            break
    
    # ── Digit ratio features ──
    domain_letters = _count_letters(hostname)
    domain_digits = _count_digits(hostname)
    digit_ratio_domain = domain_digits / max(domain_letters, 1)
    
    url_letters = _count_letters(url)
    url_digits = _count_digits(url)
    digit_ratio_url = url_digits / max(url_letters, 1)
    
    # ── Subdomain count ──
    subdomain_count = _count_subdomains(hostname)
    
    # ── Typosquatting distance ──
    typosquatting_distance = _get_min_typosquatting_distance(hostname)
    
    # ── Phishing keyword count ──
    phishing_keyword_count = 0
    for keyword in SUSPICIOUS_KEYWORDS:
        if keyword in url_lower:
            phishing_keyword_count += 1
    
    # ── Path token count ──
    path_token_count = len([p for p in full_path.split("/") if p])
    
    # ── Assemble feature vector ──
    features = np.array([
        url_length,
        hostname_length,
        path_length,
        dot_count,
        hyphen_count,
        at_count,
        question_mark_count,
        equals_count,
        percent_count,
        underscore_count,
        double_slash_count,
        has_ip_host,
        has_url_shortener,
        has_suspicious_tld,
        digit_ratio_domain,
        digit_ratio_url,
        subdomain_count,
        typosquatting_distance,
        phishing_keyword_count,
        path_token_count,
    ], dtype=np.float32)
    
    return features


def extract_url_features_dict(url):
    """
    Extract features as a dictionary (for debugging/interpretability).
    
    Args:
        url: Raw URL string
    
    Returns:
        dict: Feature names mapped to values
    """
    features_array = extract_url_features(url)
    
    feature_names = [
        "url_length",
        "hostname_length",
        "path_length",
        "dot_count",
        "hyphen_count",
        "at_count",
        "question_mark_count",
        "equals_count",
        "percent_count",
        "underscore_count",
        "double_slash_count",
        "has_ip_host",
        "has_url_shortener",
        "has_suspicious_tld",
        "digit_ratio_domain",
        "digit_ratio_url",
        "subdomain_count",
        "typosquatting_distance",
        "phishing_keyword_count",
        "path_token_count",
    ]
    
    return dict(zip(feature_names, features_array.tolist()))


# ──────────────────────────────────────────────
# Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  URL Feature Extractor — Standalone Test")
    print("=" * 60)
    print()
    
    test_urls = [
        "https://www.google.com",
        "https://www.google.com/search?q=test",
        "http://192.168.1.1/login",
        "https://bit.ly/3xM7abc",
        "https://login-verify-secure.xyz/update/account/password",
        "https://www.gooogle.com",
        "https://www.paypa1.com/login",
        "https://facbook.com/reset",
        "https://safe-site.example.com/path/to/page",
        "https://example.com/path/to/resource?id=123&name=test",
    ]
    
    for url in test_urls:
        print(f"\nURL: {url}")
        features = extract_url_features_dict(url)
        
        print("Features:")
        for name, value in features.items():
            print(f"  {name:25s}: {value}")
"""
link_analysis.py — Zyra Voice-Activated Link Analysis Module (ML-Enhanced)

Provides:
  - Smart URL retrieval: OCR from screen (WhatsApp Web) + clipboard fallback
  - ML-based URL safety analysis using LightGBM/RandomForest classifier
  - Heuristic fallback if ML model is unavailable
  - Typosquatting detection for popular domains
  - Optional VirusTotal API threat checking
  - Voice feedback via Zyra's existing TTS engine (speak.py)

Analysis tiers:
  - Safe (Probability < 0.35)
  - Suspicious (0.35 <= Probability < 0.70)
  - Dangerous (Probability >= 0.70)

Performance: <30ms for ML inference (offline feature extraction)
"""

import re
import socket
import time
from urllib.parse import urlparse

import pyperclip
import requests

from speak import speak
from screen_ocr import get_url_smart

# Import ML module
try:
    from ml_link_analyzer import load_model_once, analyze_link_ml, is_model_loaded
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("⚠ ML module not available — using heuristic-only analysis")

# Import feature extractor for fallback heuristics
try:
    from url_feature_extractor import extract_url_features
    FEATURE_EXTRACTOR_AVAILABLE = True
except ImportError:
    FEATURE_EXTRACTOR_AVAILABLE = False


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# Set this to your VirusTotal API key to enable API-based threat scanning.
# Leave as None to use ML + heuristic analysis only.
VIRUSTOTAL_API_KEY = None  # e.g. "your_api_key_here"

# ML model settings
USE_ML_FIRST = True  # Try ML first, fallback to heuristics
USE_VIRUSTOTAL_FALLBACK = True  # Check VirusTotal for uncertain cases


# ──────────────────────────────────────────────
# 1. Smart URL Retrieval (OCR + Clipboard)
# ──────────────────────────────────────────────

def get_clipboard_url():
    """
    Retrieve the current text from the system clipboard and attempt
    to extract a valid URL from it.

    Returns:
        str: The extracted URL if found, otherwise None.
    """
    try:
        text = pyperclip.paste()
    except Exception:
        return None

    if not text or not text.strip():
        return None

    text = text.strip()

    # If the clipboard text already looks like a URL, return it
    if text.startswith(("http://", "https://")):
        return text

    # If it starts with www., prepend https://
    if text.startswith("www."):
        return f"https://{text}"

    # Check if it's a bare domain like "example.com/path"
    if re.match(
        r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+"
        r"(/[^\s]*)?$",
        text,
    ):
        return f"https://{text}"

    return None


# ──────────────────────────────────────────────
# 2. URL Validation
# ──────────────────────────────────────────────

def is_valid_url(url):
    """
    Basic structural validation of a URL.

    Args:
        url: The URL string to validate.

    Returns:
        bool: True if the URL has a valid structure.
    """
    if not url:
        return False

    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


# ──────────────────────────────────────────────
# 3. Heuristic URL Safety Analysis (Fallback)
# ──────────────────────────────────────────────

# Known suspicious / high-risk TLDs often used in phishing/malware
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".gq", ".ml", ".cf", ".tk", ".click", ".download",
    ".review", ".work", ".date", ".men", ".loan", ".win", ".bid",
    ".trade", ".webcam", ".science", ".party", ".racing", ".accountant",
    ".stream", ".gdn", ".mom", ".xin", ".vip", ".pw", ".cc",
}

# Known URL shortener domains (can obscure the real destination)
URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "tiny.cc", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "shorturl.at", "t.co", "cli.gs", "yfrog.com", "migre.me",
    "ff.im", "tiny.pl", "tr.im", "v.gd", "snipurl.com", "short.to",
    "2.gp", "x.co", "budurl.com", "shorte.st", "adf.ly", "bc.vc",
    "cutt.ly", "rb.gy", "bl.ink", "short.link",
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
    if hostname_lower.startswith("www."):
        check_name = hostname_lower[4:]
    else:
        check_name = hostname_lower

    main_part = check_name.split(".")[0] if "." in check_name else check_name

    for brand_key, brand_name in POPULAR_DOMAINS.items():
        if main_part == brand_key:
            continue

        max_distance = 2 if len(brand_key) >= 8 else 1
        distance = _levenshtein_distance(main_part, brand_key)

        if 1 <= distance <= max_distance:
            return True, brand_name, f"{brand_key}.com"

        # Check with leet-speak substitutions
        substitutions = {"0": "o", "1": "l", "3": "e", "4": "a",
                         "5": "s", "7": "t", "8": "b"}
        normalized = "".join(substitutions.get(c, c) for c in main_part)
        if normalized != main_part:
            norm_distance = _levenshtein_distance(normalized, brand_key)
            if 1 <= norm_distance <= max_distance:
                return True, brand_name, f"{brand_key}.com"

    return False, None, None


def analyze_url_heuristic(url):
    """
    Perform heuristic security analysis on a URL (fallback method).

    Args:
        url: The URL string to analyze.

    Returns:
        tuple: (verdict: str, reasons: list)
    """
    if not is_valid_url(url):
        return "dangerous", ["The URL is not structurally valid."]

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    reasons = []
    risk_score = 0

    # Check 1: Suspicious TLD
    for tld in SUSPICIOUS_TLDS:
        if hostname.endswith(tld):
            reasons.append(f"Suspicious top-level domain: {tld}")
            risk_score += 3
            break

    # Check 2: IP-based host
    if _is_ip_host(hostname):
        reasons.append("URL uses a raw IP address instead of a domain name")
        risk_score += 3

    # Check 3: Missing HTTPS
    if parsed.scheme != "https":
        reasons.append("Connection is not using HTTPS (secure protocol)")
        risk_score += 1

    # Check 4: URL shortener
    for shortener in URL_SHORTENERS:
        if shortener in hostname:
            reasons.append(f"URL is shortened by {shortener} — destination is hidden")
            risk_score += 2
            break

    # Check 5: Suspicious keywords
    lower_path = path.lower()
    found_keywords = [kw for kw in SUSPICIOUS_KEYWORDS if kw in lower_path]
    if found_keywords:
        reasons.append(
            f"Contains suspicious keywords: {', '.join(found_keywords[:3])}"
        )
        risk_score += min(len(found_keywords), 3)

    # Check 6: Excessive subdomains
    subdomain_count = _count_subdomains(hostname)
    if subdomain_count >= 3:
        reasons.append(
            f"Excessive subdomains ({subdomain_count}) — possible phishing attempt"
        )
        risk_score += 2

    # Check 7: Long path
    if len(path) > 100:
        reasons.append("Unusually long URL path — may hide malicious content")
        risk_score += 1

    # Check 8: Typosquatting
    is_typo, brand_name, original_domain = _check_typosquatting(hostname)
    if is_typo:
        reasons.append(
            f"Possible typosquatting! Looks like {brand_name} but domain is different "
            f"(expected {original_domain})"
        )
        risk_score += 3

    # Determine verdict
    if risk_score >= 5:
        verdict = "dangerous"
    elif risk_score >= 2:
        verdict = "suspicious"
    else:
        verdict = "safe"

    if not reasons:
        reasons.append("No suspicious patterns detected.")

    return verdict, reasons


# ──────────────────────────────────────────────
# 4. VirusTotal API Threat Check (Optional)
# ──────────────────────────────────────────────

def check_url_virustotal(url):
    """
    Check a URL against the VirusTotal API.

    Args:
        url: The URL to check.

    Returns:
        tuple: (verdict: str, details: str)
    """
    if not VIRUSTOTAL_API_KEY:
        return "unverified", "VirusTotal API key not configured."

    api_url = "https://www.virustotal.com/api/v3/urls"
    headers = {"x-apikey": VIRUSTOTAL_API_KEY}

    try:
        # Step 1: Submit URL for analysis
        response = requests.post(
            api_url,
            headers=headers,
            data={"url": url},
            timeout=15,
        )

        if response.status_code != 200:
            return "error", f"VirusTotal API error: HTTP {response.status_code}"

        result = response.json()
        analysis_id = result.get("data", {}).get("id", "")

        if not analysis_id:
            return "error", "Could not get analysis ID from VirusTotal."

        # Step 2: Get analysis results
        analysis_url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
        analysis_response = requests.get(
            analysis_url,
            headers=headers,
            timeout=15,
        )

        if analysis_response.status_code != 200:
            return "error", f"VirusTotal analysis error: HTTP {analysis_response.status_code}"

        analysis_result = analysis_response.json()
        stats = analysis_result.get("data", {}).get("attributes", {}).get("stats", {})

        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        total = stats.get("total", 0)

        if total == 0:
            return "unverified", "No security vendors scanned this URL."

        if malicious > 0:
            return (
                "malicious",
                f"Flagged as malicious by {malicious}/{total} security vendors."
            )
        elif suspicious > 0:
            return (
                "suspicious",
                f"Flagged as suspicious by {suspicious}/{total} security vendors."
            )
        else:
            return (
                "safe",
                f"Cleared by all {total} security vendors."
            )

    except requests.exceptions.Timeout:
        return "error", "VirusTotal API request timed out."
    except requests.exceptions.ConnectionError:
        return "error", "Could not connect to VirusTotal API."
    except Exception as e:
        return "error", f"VirusTotal check failed: {e}"


# ──────────────────────────────────────────────
# 5. ML-Enhanced Analysis
# ──────────────────────────────────────────────

def analyze_link_ml_enhanced(url):
    """
    Analyze URL using ML model with heuristic fallback.
    
    Args:
        url: URL string to analyze
    
    Returns:
        tuple: (verdict: str, reasons: list, metadata: dict)
    """
    metadata = {
        'method': 'unknown',
        'probability': 0.0,
        'confidence': 'low',
    }
    
    # Try ML analysis first
    if USE_ML_FIRST and ML_AVAILABLE:
        try:
            result = analyze_link_ml(url, use_virustotal=False)
            
            if result and result.get('ml_available'):
                metadata['method'] = 'ml'
                metadata['probability'] = result.get('probability', 0.0)
                metadata['confidence'] = result.get('confidence', 'low')
                metadata['execution_time_ms'] = result.get('execution_time_ms', 0.0)
                
                return result['verdict'], result['reasons'], metadata
        except Exception as e:
            print(f"⚠ ML analysis failed: {e}, falling back to heuristics")
    
    # Fallback to heuristic analysis
    verdict, reasons = analyze_url_heuristic(url)
    metadata['method'] = 'heuristic'
    
    # Convert heuristic risk score to probability estimate
    # This is a rough mapping for consistency
    if verdict == 'dangerous':
        metadata['probability'] = 0.8
        metadata['confidence'] = 'medium'
    elif verdict == 'suspicious':
        metadata['probability'] = 0.5
        metadata['confidence'] = 'medium'
    else:
        metadata['probability'] = 0.1
        metadata['confidence'] = 'high'
    
    return verdict, reasons, metadata


# ──────────────────────────────────────────────
# 6. Orchestrator: Full Pipeline
# ──────────────────────────────────────────────

def analyze_link():
    """
    Full voice-activated link analysis pipeline:
      1. Get URL from screen OCR (WhatsApp Web) or clipboard fallback
      2. Validate it
      3. Run ML analysis (with heuristic fallback)
      4. Optionally check with VirusTotal API
      5. Speak the result back to the user

    This is the main entry point to call from main.py.
    """
    print("\n🔗 Zyra is analysing the link...")
    pipeline_start = time.time()

    # Step 1: Get URL from screen (OCR) or clipboard
    url = get_url_smart()

    if not url:
        speak("No valid link found on your screen or clipboard.")
        print("   ❌ No URL found.")
        return

    print(f"   📋 URL: {url}")

    # Step 2: Validate URL structure
    if not is_valid_url(url):
        speak("The link does not appear to be a valid URL.")
        print("   ❌ Invalid URL structure.")
        return

    # Step 3: Run ML-enhanced analysis
    verdict, reasons, metadata = analyze_link_ml_enhanced(url)
    
    analysis_method = metadata.get('method', 'unknown')
    probability = metadata.get('probability', 0.0)
    execution_time = metadata.get('execution_time_ms', 0.0)
    
    print(f"   🧠 Analysis method: {analysis_method.upper()}")
    if analysis_method == 'ml':
        print(f"   ⚡ ML inference: {execution_time:.2f}ms")
        print(f"   📊 Phishing probability: {probability*100:.1f}%")

    # Step 4: Optionally run VirusTotal check
    vt_verdict = None
    vt_details = None
    
    if USE_VIRUSTOTAL_FALLBACK and VIRUSTOTAL_API_KEY:
        print("   🔬 Checking with VirusTotal API...")
        vt_verdict, vt_details = check_url_virustotal(url)
        print(f"   VirusTotal: {vt_verdict.upper()} — {vt_details}")

    # Step 5: Determine final verdict and speak
    # VirusTotal overrides if it found malicious
    if vt_verdict == "malicious":
        final_verdict = "dangerous"
        speak("Warning! The link has been flagged as malicious by security scanners.")
    elif vt_verdict == "suspicious":
        final_verdict = "suspicious"
        speak("Caution. The link appears suspicious according to security scanners.")
    elif verdict == "dangerous":
        final_verdict = "dangerous"
        if analysis_method == 'ml':
            speak(f"Warning! This link appears dangerous. The security model detected a {probability*100:.0f}% probability of phishing. I recommend avoiding this website.")
        else:
            speak("Warning! The link from your screen appears unsafe.")
    elif verdict == "suspicious":
        final_verdict = "suspicious"
        if analysis_method == 'ml':
            speak(f"Caution. This link appears somewhat suspicious. The security model detected a {probability*100:.0f}% probability of phishing. Please verify before proceeding.")
        else:
            speak("Caution. The link from your screen appears suspicious.")
    else:
        final_verdict = "safe"
        if analysis_method == 'ml':
            speak(f"I have analyzed the link. It appears to be safe. The security model detected only a {probability*100:.0f}% probability of phishing.")
        else:
            speak("I have analyzed the link. It appears to be safe.")

    # Print detailed results to console
    icon = {"safe": "✅", "suspicious": "⚠️", "dangerous": "🚫"}[final_verdict]
    print(f"\n   {icon} Final Verdict: {final_verdict.upper()}")

    print(f"   📊 Analysis Details:")
    for reason in reasons:
        print(f"      • {reason}")

    if vt_details:
        print(f"   🔬 VirusTotal: {vt_details}")
    
    total_time = time.time() - pipeline_start
    print(f"   ⏱️  Total pipeline time: {total_time*1000:.1f}ms")

    return final_verdict, url, reasons


# ──────────────────────────────────────────────
# 7. Model Initialization
# ──────────────────────────────────────────────

def initialize_ml_model():
    """
    Initialize ML model at system startup.
    Call this function during Zyra initialization.
    
    Returns:
        bool: True if ML model loaded successfully
    """
    if not ML_AVAILABLE:
        print("ℹ️  ML module not available — using heuristic analysis")
        return False
    
    return load_model_once()


# ──────────────────────────────────────────────
# 8. Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("  Zyra Link Analysis — Standalone Test (ML-Enhanced)")
    print("=" * 70)
    print()
    
    # Initialize ML model
    print("📦 Initializing ML model...")
    ml_loaded = initialize_ml_model()
    print()
    
    print("Testing with sample URLs...")
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
        print(f"\nTesting: {url}")
        
        # Use ML-enhanced analysis
        verdict, reasons, metadata = analyze_link_ml_enhanced(url)
        
        icon = {"safe": "✅", "suspicious": "⚠️", "dangerous": "🚫"}[verdict]
        print(f"{icon} {verdict.upper():12s} | Method: {metadata['method']}")
        
        if metadata['method'] == 'ml':
            print(f"   Probability: {metadata['probability']*100:.1f}%")
            print(f"   Confidence: {metadata['confidence']}")
            if 'execution_time_ms' in metadata:
                print(f"   Inference time: {metadata['execution_time_ms']:.2f}ms")
        
        for r in reasons:
            print(f"    • {r}")
        print()

    print("=" * 70)
    print("Now testing smart URL retrieval (OCR + clipboard)...")
    print("(Make sure a URL is visible on screen or in clipboard)")
    print("=" * 70)

    url = get_url_smart()
    if url:
        print(f"✅ Retrieved URL: {url}")
        verdict, reasons, metadata = analyze_link_ml_enhanced(url)
        print(f"Verdict: {verdict.upper()}")
        for r in reasons:
            print(f"  • {r}")
    else:
        print("ℹ️  No URL found on screen or clipboard.")
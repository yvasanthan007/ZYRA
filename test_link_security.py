"""
test_link_security.py — Zyra Link Security Pipeline Demo

Demonstrates the complete pipeline:
  1. Screen OCR capture (or clipboard fallback)
  2. URL extraction
  3. Heuristic analysis with 8-check scoring engine
  4. Optional VirusTotal API integration
  5. Voice feedback via TTS

This is a standalone demonstration of the link security feature.
"""

import os
import sys

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screen_ocr import get_url_smart, extract_urls_from_text
from link_analysis import (
    analyze_url,
    check_url_virustotal,
    VIRUSTOTAL_API_KEY,
    SUSPICIOUS_TLDS,
    URL_SHORTENERS,
    SUSPICIOUS_KEYWORDS,
    POPULAR_DOMAINS,
)


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_url_regex():
    """Test the URL extraction regex with various inputs."""
    print_section("TEST 1: URL Regex Extraction")

    test_cases = [
        "Check out https://www.google.com for more info",
        "Visit bit.ly/3xM7abc for the deal",
        "Here is the link: example.com/login",
        "No URLs here at all",
        "Multiple: https://safe.com and http://evil.tk/login",
        "IP address: http://192.168.1.1/admin",
        "With port: https://example.com:8080/path",
        "Complex: https://sub.domain.example.co.uk/path?query=value",
    ]

    for text in test_cases:
        urls = extract_urls_from_text(text)
        if urls:
            print(f"\n  📝 Input: {text[:60]}...")
            for url in urls:
                print(f"     ✓ Extracted: {url}")
        else:
            print(f"\n  📝 Input: {text[:60]}...")
            print(f"     ✗ No URLs found")


def test_heuristic_analysis():
    """Test the 8-check heuristic analysis engine."""
    print_section("TEST 2: Heuristic Analysis (8 Checks)")

    print("\n  Configuration:")
    print(f"    • Suspicious TLDs: {len(SUSPICIOUS_TLDS)} configured")
    print(f"    • URL Shorteners: {len(URL_SHORTENERS)} configured")
    print(f"    • Suspicious Keywords: {len(SUSPICIOUS_KEYWORDS)} configured")
    print(f"    • Popular Brands: {len(POPULAR_DOMAINS)} configured")
    print(f"    • VirusTotal API: {'Configured' if VIRUSTOTAL_API_KEY else 'Not configured'}")

    test_urls = [
        ("https://www.google.com", "Safe - legitimate site"),
        ("http://192.168.1.1/login", "IP-based host + no HTTPS"),
        ("https://bit.ly/3xM7abc", "URL shortener"),
        ("https://login-verify-secure.xyz/update/account/password", "Suspicious TLD + keywords"),
        ("https://www.amazon.com/dp/B08N5WRWNW", "Safe - legitimate e-commerce"),
        ("http://suspicious-login-page.tk/secure/verify", "Suspicious TLD + no HTTPS + keywords"),
        ("https://www.gooogle.com", "Typosquatting: google → gooogle"),
        ("https://www.paypa1.com/login", "Typosquatting: paypal → paypa1 (leet)"),
        ("https://facbook.com/reset", "Typosquatting: facebook → facbook"),
        ("https://sub.domain.example.xyz/path/to/login", "Excessive subdomains + suspicious TLD"),
    ]

    print("\n  Analysis Results:")
    print("-" * 70)

    for url, description in test_urls:
        res = analyze_url(url)
        if isinstance(res, dict):
            verdict = res.get("verdict", "Safe")
            score = res.get("score", 0)
            reasons = [c.get("details", "") for c in res.get("checks", [])]
        else:
            verdict, reasons = res
            # Calculate score from reasons
            score = 0
            for reason in reasons:
                if "Suspicious top-level domain" in reason:
                    score += 3
                elif "raw IP address" in reason:
                    score += 3
                elif "not using HTTPS" in reason:
                    score += 1
                elif "shortened by" in reason:
                    score += 2
                elif "suspicious keywords" in reason:
                    score += 2
                elif "Excessive subdomains" in reason:
                    score += 2
                elif "long URL path" in reason:
                    score += 1
                elif "typosquatting" in reason.lower():
                    score += 3

        icon = {"safe": "✅", "suspicious": "⚠️", "dangerous": "🚫"}.get(verdict.lower(), "❓")

        print(f"\n  {icon} {verdict.upper()} (Score: {score})")
        print(f"     URL: {url}")
        print(f"     Test: {description}")
        print(f"     Reasons:")
        for reason in reasons:
            print(f"       • {reason}")


def test_virustotal_integration():
    """Test VirusTotal API integration (if configured)."""
    print_section("TEST 3: VirusTotal API Integration")

    if not VIRUSTOTAL_API_KEY:
        print("\n  ⚠️  VirusTotal API key not configured.")
        print("  To enable:")
        print("    1. Get an API key from https://www.virustotal.com/")
        print("    2. Set environment variable: VIRUSTOTAL_API_KEY=your_key")
        print("    3. Or modify link_analysis.py: VIRUSTOTAL_API_KEY = 'your_key'")
        return

    print(f"\n  ✓ VirusTotal API key configured")
    print("  Testing with a known safe URL...")

    test_url = "https://www.google.com"
    verdict, details = check_url_virustotal(test_url)

    print(f"\n  URL: {test_url}")
    print(f"  Verdict: {verdict.upper()}")
    print(f"  Details: {details}")


def test_screen_capture():
    """Test screen capture and OCR (optional - requires screen with visible URL)."""
    print_section("TEST 4: Screen Capture + OCR")

    print("\n  This test attempts to capture your screen and extract URLs.")
    print("  For best results, have a URL visible on your screen.")
    print()

    try:
        import mss
        import easyocr

        print("  ✓ mss and easyocr are installed")
        print("  📸 Capturing screen...")

        url = get_url_smart()

        if url:
            print(f"\n  ✅ URL found: {url}")

            # Analyze the found URL
            verdict, reasons = analyze_url(url)
            print(f"\n  📊 Analysis: {verdict.upper()}")
            for reason in reasons:
                print(f"     • {reason}")
        else:
            print("\n  ℹ️  No URL found on screen or clipboard.")
            print("  This is normal if no links are currently visible.")

    except ImportError as e:
        print(f"\n  ⚠️  Required packages not installed: {e}")
        print("  Install with: pip install mss easyocr")


def print_summary():
    """Print implementation summary."""
    print_section("IMPLEMENTATION SUMMARY")

    print("""
  ✓ screen_ocr.py
    • Screen capture using mss (multi-monitor aware)
    • OCR text extraction using EasyOCR
    • Robust URL regex extraction
    • Clipboard fallback when OCR finds nothing
    • Returns cleaned URL or None

  ✓ link_analysis.py
    • 8-check heuristic scoring engine:
      1. Suspicious TLD (+3 points)
      2. IP-based host (+3 points)
      3. Typosquatting & Leet-speak (+3 points)
      4. URL Shortener (+2 points)
      5. Excessive Subdomains (+2 points)
      6. Suspicious Keywords (+2 points)
      7. Missing HTTPS (+1 point)
      8. Long/Obfuscated Path (+1 point)
    • Verdict classification:
      - 0-1 points: Safe
      - 2-4 points: Suspicious
      - 5+ points: Dangerous
    • Optional VirusTotal API integration
    • Voice feedback via TTS

  ✓ requirements.txt
    • All dependencies listed with minimum versions

  Usage Examples:
    # Run standalone tests
    python test_link_security.py

    # Use in your code
    from link_analysis import analyze_url, get_url_smart

    # Analyze a specific URL
    verdict, reasons = analyze_url("https://example.com")
    print(f"Verdict: {verdict}")

    # Get URL from screen/clipboard and analyze
    url = get_url_smart()
    if url:
        verdict, reasons = analyze_url(url)
        print(f"Found URL: {url}")
        print(f"Verdict: {verdict}")
        for reason in reasons:
            print(f"  • {reason}")

    # Enable VirusTotal (optional)
    import os
    os.environ["VIRUSTOTAL_API_KEY"] = "your_api_key"
    from link_analysis import check_url_virustotal
    verdict, details = check_url_virustotal("https://example.com")
    """)


if __name__ == "__main__":
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "ZYRA LINK SECURITY - PIPELINE DEMO" + " " * 20 + "║")
    print("╚" + "═" * 68 + "╝")

    # Run all tests
    test_url_regex()
    test_heuristic_analysis()
    test_virustotal_integration()

    # Optional: Screen capture test (comment out if not needed)
    # test_screen_capture()

    print_summary()

    print("\n" + "=" * 70)
    print("  Demo complete!")
    print("=" * 70 + "\n")
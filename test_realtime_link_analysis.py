"""
test_realtime_link_analysis.py — Comprehensive Test Suite for Zyra Link Analysis

Tests the complete real-time link analysis pipeline:
  1. Screen OCR URL extraction
  2. Clipboard fallback
  3. 8-check heuristic analysis
  4. Voice response generation
  5. Integration with zyra_handler

Run this file directly to test all components:
    python test_realtime_link_analysis.py
"""

import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screen_ocr import (
    capture_screen,
    extract_text_from_image,
    extract_urls_from_text,
    get_url_from_clipboard,
    get_active_url,
)
from link_analysis import (
    analyze_url,
    analyze_link,
    _is_ip_host,
    _count_subdomains,
    _levenshtein_distance,
    _check_typosquatting,
    VIRUSTOTAL_API_KEY,
)
from zyra_handler import (
    handle_analyze_link_intent,
    is_link_analysis_intent,
    quick_analyze_url,
)


# ──────────────────────────────────────────────
# Test Utilities
# ──────────────────────────────────────────────

def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_test(test_name, passed, details=""):
    """Print test result with status."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {test_name}")
    if details:
        print(f"         → {details}")


# ──────────────────────────────────────────────
# Test Suite
# ──────────────────────────────────────────────

def test_url_regex_extraction():
    """Test URL regex pattern matching."""
    print_section("TEST 1: URL Regex Extraction")
    
    test_cases = [
        ("Check out https://www.google.com for more info", 
         ["https://www.google.com"], "Standard HTTPS URL"),
        ("Visit bit.ly/3xM7abc for the deal", 
         ["https://bit.ly/3xM7abc"], "URL shortener"),
        ("Here is the link: example.com/login", 
         ["https://example.com/login"], "Bare domain with path"),
        ("No URLs here at all", 
         [], "No URLs present"),
        ("Multiple: https://safe.com and http://evil.tk/login", 
         ["https://safe.com", "http://evil.tk/login"], "Multiple URLs (preserves protocol)"),
        ("Check www.example.com", 
         ["https://www.example.com"], "www prefix"),
    ]
    
    all_passed = True
    for text, expected, description in test_cases:
        result = extract_urls_from_text(text)
        passed = result == expected
        all_passed = all_passed and passed
        print_test(description, passed, f"Expected: {expected}, Got: {result}")
    
    return all_passed


def test_helper_functions():
    """Test internal helper functions."""
    print_section("TEST 2: Helper Functions")
    
    all_passed = True
    
    # Test _is_ip_host
    test_cases_ip = [
        ("192.168.1.1", True, "Valid IPv4"),
        ("10.0.0.1", True, "Valid IPv4 private"),
        ("google.com", False, "Domain name"),
        ("example.com", False, "Domain name"),
    ]
    
    for host, expected, desc in test_cases_ip:
        result = _is_ip_host(host)
        passed = result == expected
        all_passed = all_passed and passed
        print_test(f"_is_ip_host({host})", passed, f"Expected: {expected}, Got: {result}")
    
    # Test _count_subdomains
    test_cases_sub = [
        ("www.google.com", 0, "Single subdomain (www)"),
        ("mail.google.com", 1, "One subdomain"),
        ("a.b.c.google.com", 3, "Three subdomains"),
        ("google.com", 0, "No subdomains"),
    ]
    
    for host, expected, desc in test_cases_sub:
        result = _count_subdomains(host)
        passed = result == expected
        all_passed = all_passed and passed
        print_test(f"_count_subdomains({host})", passed, f"Expected: {expected}, Got: {result}")
    
    # Test _levenshtein_distance
    lev_tests = [
        ("google", "gooogle", 1, "One extra letter"),
        ("facebook", "facbook", 1, "One missing letter"),
        ("paypal", "paypa1", 1, "Leet speak substitution"),
        ("google", "facebook", 8, "Completely different"),
    ]
    
    for s1, s2, expected, desc in lev_tests:
        result = _levenshtein_distance(s1, s2)
        passed = result == expected
        all_passed = all_passed and passed
        print_test(f"Levenshtein('{s1}', '{s2}')", passed, f"Expected: {expected}, Got: {result}")
    
    # Test _check_typosquatting
    typo_tests = [
        ("www.gooogle.com", True, "Google typosquatting"),
        ("www.paypa1.com", True, "PayPal typosquatting"),
        ("www.facbook.com", True, "Facebook typosquatting"),
        ("www.google.com", False, "Legitimate Google"),
        ("www.example.com", False, "Unknown domain"),
    ]
    
    for host, should_detect, desc in typo_tests:
        is_typo, brand, orig = _check_typosquatting(host)
        passed = is_typo == should_detect
        all_passed = all_passed and passed
        details = f"Detected: {is_typo}, Brand: {brand}" if is_typo else "No typosquatting"
        print_test(f"Typosquatting check: {host}", passed, details)
    
    return all_passed


def test_heuristic_analysis():
    """Test the 8-check heuristic analysis pipeline."""
    print_section("TEST 3: 8-Check Heuristic Analysis")
    
    test_cases = [
        # (url, expected_verdict, min_score, description)
        ("https://www.google.com", "Safe", 0, "Legitimate Google"),
        ("http://192.168.1.1/login", "Dangerous", 4, "IP-based host"),
        ("https://bit.ly/3xM7abc", "Suspicious", 2, "URL shortener"),
        ("https://login-verify-secure.xyz/update/account/password", 
         "Dangerous", 5, "Suspicious TLD + keywords"),
        ("https://www.gooogle.com", "Suspicious", 3, "Typosquatting"),
        ("https://www.paypa1.com/login", "Suspicious", 3, "Typosquatting PayPal"),
        ("http://example.com", "Safe", 1, "HTTP but no other issues"),
    ]
    
    all_passed = True
    for url, expected_verdict, min_score, description in test_cases:
        result = analyze_url(url)
        verdict_match = result["verdict"] == expected_verdict
        score_match = result["score"] >= min_score
        passed = verdict_match and score_match
        
        all_passed = all_passed and passed
        details = f"Verdict: {result['verdict']} (expected: {expected_verdict}), Score: {result['score']}"
        print_test(description, passed, details)
    
    return all_passed


def test_speech_text_generation():
    """Test that speech text matches exact requirements."""
    print_section("TEST 4: Speech Text Generation")
    
    test_cases = [
        ("https://www.google.com", "Safe", 
         "I've analyzed the link: https://www.google.com. It appears to be safe."),
        ("http://suspicious.tk/login", "Suspicious",
         "Caution. The link http://suspicious.tk/login from your screen appears suspicious."),
        ("http://evil.xyz/malware", "Dangerous",
         "Warning! The link http://evil.xyz/malware from your screen appears unsafe."),
    ]
    
    all_passed = True
    for url, verdict, expected_speech in test_cases:
        result = analyze_url(url)
        # Manually set verdict to test speech generation
        result["verdict"] = verdict
        from link_analysis import _generate_speech_text
        speech = _generate_speech_text(url, verdict, result["score"])
        
        passed = speech == expected_speech
        all_passed = all_passed and passed
        print_test(f"Speech text for {verdict}", passed, f"Got: {speech[:60]}...")
    
    return all_passed


def test_trigger_detection():
    """Test link analysis intent detection."""
    print_section("TEST 5: Trigger Phrase Detection")
    
    test_cases = [
        ("Zyra analyze this link", True, "Analyze trigger"),
        ("Zyra check this link", True, "Check trigger"),
        ("Is this link safe?", True, "Safety question"),
        ("Analyze the URL http://example.com", True, "URL in text"),
        ("What's the weather?", False, "Unrelated command"),
        ("Open Chrome", False, "Unrelated command"),
    ]
    
    all_passed = True
    for text, expected, description in test_cases:
        result = is_link_analysis_intent(text)
        passed = result == expected
        all_passed = all_passed and passed
        print_test(description, passed, f"Expected: {expected}, Got: {result}")
    
    return all_passed


def test_no_url_scenario():
    """Test behavior when no URL is found."""
    print_section("TEST 6: No URL Found Scenario")
    
    # Mock get_active_url in link_analysis module
    import link_analysis
    original_func = link_analysis.get_active_url
    
    def mock_get_active_url():
        return None
    
    link_analysis.get_active_url = mock_get_active_url
    
    try:
        result = analyze_link()
        passed = (
            result["url"] is None and
            result["verdict"] == "Not Found" and
            "couldn't find" in result["speech_text"].lower()
        )
        print_test("No URL found handling", passed, 
                   f"Verdict: {result['verdict']}, Speech: {result['speech_text'][:50]}...")
        return passed
    finally:
        link_analysis.get_active_url = original_func


def test_score_verdict_mapping():
    """Test that score-to-verdict mapping is correct."""
    print_section("TEST 7: Score-to-Verdict Mapping")
    
    # Create URLs with known characteristics to test score boundaries
    
    # Score 0-1: Safe
    safe_url = "https://www.google.com"
    result = analyze_url(safe_url)
    passed_safe = result["verdict"] == "Safe" and result["score"] <= 1
    print_test("Safe verdict (score 0-1)", passed_safe, 
               f"Score: {result['score']}, Verdict: {result['verdict']}")
    
    # Score 2-4: Suspicious
    suspicious_url2 = "https://bit.ly/test"  # Shortener = score 2
    result2 = analyze_url(suspicious_url2)
    passed_suspicious = result2["verdict"] == "Suspicious" and 2 <= result2["score"] <= 4
    print_test("Suspicious verdict (score 2-4)", passed_suspicious,
               f"Score: {result2['score']}, Verdict: {result2['verdict']}")
    
    # Score 5+: Dangerous
    dangerous_url = "http://login-verify.tk/secure/account/password/update"
    result3 = analyze_url(dangerous_url)
    passed_dangerous = result3["verdict"] == "Dangerous" and result3["score"] >= 5
    print_test("Dangerous verdict (score 5+)", passed_dangerous,
               f"Score: {result3['score']}, Verdict: {result3['verdict']}")
    
    return passed_safe and passed_suspicious and passed_dangerous


def test_virustotal_config():
    """Test VirusTotal configuration."""
    print_section("TEST 8: VirusTotal Configuration")
    
    print(f"   VirusTotal API Key: {'Configured' if VIRUSTOTAL_API_KEY else 'Not configured'}")
    print(f"   (Set VIRUSTOTAL_API_KEY environment variable to enable)")
    
    # Test that the function exists and is callable
    from link_analysis import _check_virustotal
    result = _check_virustotal("https://www.google.com")
    print_test("VirusTotal check function", True, 
               f"Returns: {result} (safe when not configured)")
    
    return True


def test_integration_handler():
    """Test the main integration handler (without actually speaking)."""
    print_section("TEST 9: Integration Handler (zyra_handler)")
    
    # Mock speak at the source module level
    import speak as speak_module
    original_speak = speak_module.speak
    spoken_texts = []
    
    def mock_speak(text):
        spoken_texts.append(text)
        print(f"   [MOCK SPEAK] {text}")
    
    speak_module.speak = mock_speak
    
    # Also mock in zyra_handler since it imports speak
    import zyra_handler
    zyra_handler.speak = mock_speak
    
    # Mock get_active_url in zyra_handler module (where it's actually used)
    import link_analysis
    original_handler_func = zyra_handler.get_active_url
    original_link_func = link_analysis.get_active_url
    
    def mock_get_active_url():
        return "https://www.google.com"
    
    zyra_handler.get_active_url = mock_get_active_url
    link_analysis.get_active_url = mock_get_active_url
    
    try:
        result = zyra_handler.handle_analyze_link_intent("Zyra analyze this link")
        
        passed = (
            result["success"] and
            result["url"] == "https://www.google.com" and
            result["verdict"] == "Safe" and
            len(spoken_texts) > 0 and
            "safe" in spoken_texts[0].lower()
        )
        
        print_test("Handler integration", passed,
                   f"Verdict: {result['verdict']}, Spoken: {len(spoken_texts)} messages")
        
        return passed
    finally:
        speak_module.speak = original_speak
        zyra_handler.speak = original_speak
        zyra_handler.get_active_url = original_handler_func
        link_analysis.get_active_url = original_link_func


def test_edge_cases():
    """Test edge cases and error handling."""
    print_section("TEST 10: Edge Cases")
    
    all_passed = True
    
    # Empty URL
    result = analyze_url("")
    passed = result["verdict"] == "Safe" and result["score"] == 0
    print_test("Empty URL handling", passed, f"Verdict: {result['verdict']}")
    all_passed = all_passed and passed
    
    # URL with only scheme
    result = analyze_url("http://")
    passed = result["verdict"] in ["Safe", "Suspicious"]
    print_test("Invalid URL handling", passed, f"Verdict: {result['verdict']}")
    all_passed = all_passed and passed
    
    # Very long URL path
    long_path_url = "https://example.com/" + "a" * 150
    result = analyze_url(long_path_url)
    passed = result["score"] >= 1  # Should trigger long path check
    print_test("Long path detection", passed, f"Score: {result['score']}")
    all_passed = all_passed and passed
    
    return all_passed


# ──────────────────────────────────────────────
# Main Test Runner
# ──────────────────────────────────────────────

def run_all_tests():
    """Run all test suites and report results."""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║          ZYRA REAL-TIME LINK ANALYSIS — TEST SUITE                  ║
╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    tests = [
        ("URL Regex Extraction", test_url_regex_extraction),
        ("Helper Functions", test_helper_functions),
        ("Heuristic Analysis", test_heuristic_analysis),
        ("Speech Text Generation", test_speech_text_generation),
        ("Trigger Detection", test_trigger_detection),
        ("No URL Scenario", test_no_url_scenario),
        ("Score-Verdict Mapping", test_score_verdict_mapping),
        ("VirusTotal Config", test_virustotal_config),
        ("Integration Handler", test_integration_handler),
        ("Edge Cases", test_edge_cases),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n❌ ERROR in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print_section("TEST SUMMARY")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} | {test_name}")
    
    print(f"\n{'=' * 70}")
    print(f"Results: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("🎉 ALL TESTS PASSED!")
    else:
        print(f"⚠️  {total_count - passed_count} test(s) failed")
    
    print("=" * 70)
    
    return passed_count == total_count


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
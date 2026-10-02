"""
zyra_handler.py — Zyra Link Analysis Intent Handler

Main integration handler that ties together:
  - screen_ocr.py (URL capture from screen/clipboard)
  - link_analysis.py (8-check heuristic analysis + VirusTotal)
  - speak.py (Text-to-Speech output)

This module provides the handle_analyze_link_intent() function that:
  1. Listens for trigger phrases like "Zyra analyze this link"
  2. Captures URL from screen OCR or clipboard
  3. Runs the complete security analysis
  4. Speaks the exact verdict directly to the user
"""

import sys
from typing import Optional

from screen_ocr import get_active_url
from link_analysis import analyze_url, VIRUSTOTAL_API_KEY
from speak import speak


def _url_from_text(user_text: Optional[str]) -> Optional[str]:
    """Return the first URL spoken/typed in the command, or None.

    Speech recognition renders URLs as real characters ("http://paypal.com"),
    so when the user actually says the link we analyze it directly instead of
    paying the slow screen-OCR capture (which can take 40+ seconds and often
    finds nothing).
    """
    if not user_text:
        return None
    try:
        from backend.link_security import extract_url
    except Exception:
        return None
    try:
        return extract_url(user_text)
    except Exception:
        return None


# ──────────────────────────────────────────────
# Trigger Phrase Detection
# ──────────────────────────────────────────────

LINK_ANALYSIS_TRIGGERS = [
    "analyse the link",
    "analyze the link",
    "analyse this link",
    "analyze this link",
    "analyse the url",
    "analyze the url",
    "analyse this url",
    "analyze this url",
    "check this link",
    "check the link",
    "check this url",
    "check the url",
    "scan this link",
    "scan the link",
    "is this link safe",
    "is this url safe",
    "zyra analyze",
    "zyra check",
]


def is_link_analysis_intent(text: str) -> bool:
    """
    Check if the user's text matches a link analysis trigger phrase.
    
    Args:
        text: User's voice command or text input
        
    Returns:
        bool: True if this is a link analysis request
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Check for trigger phrases
    for trigger in LINK_ANALYSIS_TRIGGERS:
        if trigger in text_lower:
            return True
    
    # Also trigger if text contains a URL directly
    if "http://" in text_lower or "https://" in text_lower or "www." in text_lower:
        return True
    
    return False


# ──────────────────────────────────────────────
# Main Handler Function
# ──────────────────────────────────────────────

def handle_analyze_link_intent(user_text: Optional[str] = None) -> dict:
    """
    Main entry point for link analysis intent handling.
    
    This function:
    1. Extracts the URL from the command text when the user says it, and
       otherwise falls back to screen OCR / clipboard capture
    2. Runs the 8-check heuristic analysis pipeline
    3. Optionally checks VirusTotal (if API key configured)
    4. Speaks the exact verdict directly to the user
    5. Returns structured result
    
    Args:
        user_text: Optional user command text (source of the URL when spoken)
        
    Returns:
        dict: Complete analysis result containing:
            - url: The analyzed URL (or None if not found)
            - score: Total risk score (0+)
            - verdict: "Safe", "Suspicious", "Dangerous", or "Not Found"
            - speech_text: Exact string that was spoken to the user
            - checks: List of individual check results
            - success: Whether analysis completed successfully
    """
    print("\n" + "=" * 60)
    print("🔗 ZYRA LINK ANALYSIS — REAL-TIME SCREEN SCAN")
    print("=" * 60)
    
    # Step 1: Prefer the URL spoken in the command; it is instant and exact.
    url = _url_from_text(user_text)
    if url:
        print(f"\n✅ URL spoken in command: {url}")
    else:
        # No URL in the command — capture it from screen OCR or clipboard.
        print("\n📸 Step 1: Capturing screen for URL detection...")
        url = get_active_url()
    
    # Step 2: Handle no URL found case
    if not url:
        speech_text = "I couldn't find any URL on your screen or in your clipboard."
        print(f"\n❌ {speech_text}")
        speak(speech_text)
        
        return {
            "url": None,
            "score": 0,
            "verdict": "Not Found",
            "speech_text": speech_text,
            "checks": [],
            "success": False
        }
    
    print(f"\n✅ URL detected: {url}")
    
    # Step 3: Run heuristic analysis
    print("\n🔍 Step 2: Running security analysis...")
    result = analyze_url(url)
    
    # Step 4: VirusTotal is already merged into the analysis above when an
    # API key is configured (see link_analysis.analyze_url). Derive the
    # override flag from the returned checks instead of scanning twice.
    vt_override = any(
        c.get("check") == "VirusTotal" and c.get("score", 0) >= 5
        for c in result.get("checks", [])
    )
    vt_flagged = any(c.get("check") == "VirusTotal"
                     for c in result.get("checks", []))
    if not VIRUSTOTAL_API_KEY:
        print("\n\u2139\ufe0f  Step 3: VirusTotal not configured (skipping)")
    elif vt_override:
        print("   \u26a0\ufe0f  VirusTotal: MALICIOUS")
    elif vt_flagged:
        print("   \u26a0\ufe0f  VirusTotal: SUSPICIOUS")
    else:
        print("   \u2705 VirusTotal: Clean")
    
    # Step 5: Speak the result directly to user
    print(f"\n🗣️  Step 4: Speaking verdict...")
    print(f"   Speech text: {result['speech_text']}")
    speak(result['speech_text'])
    
    # Step 6: Print detailed analysis to console
    print("\n" + "=" * 60)
    print("📊 DETAILED ANALYSIS REPORT")
    print("=" * 60)
    print(f"\n🔗 URL: {result['url']}")
    print(f"📈 Risk Score: {result['score']}")
    print(f"⚖️  Verdict: {result['verdict']}")
    
    if result['checks']:
        print(f"\n🔍 Checks Triggered ({len(result['checks'])}):")
        for i, check in enumerate(result['checks'], 1):
            print(f"   {i}. {check['check']} (+{check['score']} points)")
            print(f"      → {check['details']}")
    
    print("\n" + "=" * 60)
    
    # Return structured result
    return {
        "url": result['url'],
        "score": result['score'],
        "verdict": result['verdict'],
        "speech_text": result['speech_text'],
        "checks": result['checks'],
        "success": True,
        "virustotal_override": vt_override
    }


def quick_analyze_url(url: str) -> dict:
    """
    Quick analysis of a specific URL (bypasses screen capture).
    Useful for testing or direct URL analysis.
    
    Args:
        url: The URL to analyze
        
    Returns:
        dict: Analysis result with speech_text
    """
    print(f"\n🔗 Quick analyzing URL: {url}")
    
    result = analyze_url(url)
    
    # Speak the result
    speak(result['speech_text'])
    
    return result


# ──────────────────────────────────────────────
# Command Line Interface
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════╗
║     ZYRA LINK ANALYSIS HANDLER — TEST        ║
╚══════════════════════════════════════════════╝
    """)
    
    print("Options:")
    print("  1. Test with screen capture (OCR + clipboard)")
    print("  2. Test with specific URL")
    print("  3. Exit")
    print()
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        # Test full pipeline with screen capture
        result = handle_analyze_link_intent()
        
        print("\n" + "=" * 60)
        print("RESULT SUMMARY")
        print("=" * 60)
        print(f"Verdict: {result['verdict']}")
        print(f"Speech: {result['speech_text']}")
        print(f"Success: {result['success']}")
        
    elif choice == "2":
        # Test with specific URL
        url = input("\nEnter URL to analyze: ").strip()
        if url:
            result = quick_analyze_url(url)
            
            print("\n" + "=" * 60)
            print("RESULT SUMMARY")
            print("=" * 60)
            print(f"Verdict: {result['verdict']}")
            print(f"Speech: {result['speech_text']}")
        else:
            print("No URL provided.")
    
    else:
        print("Exiting...")
        sys.exit(0)
"""
screen_ocr.py — Zyra Screen Capture & OCR Link Extraction Module

Captures the active screen region (or full screen) and extracts URLs
using EasyOCR (pure Python, no external binary required).

Workflow:
  1. Capture the screen using mss (fast, multi-monitor aware)
  2. Run EasyOCR on the captured image to extract text
  3. Regex-filter all valid URLs from the extracted text
  4. Return the first valid URL found (or None)

Fallback:
  - If no URL found on screen, fetch text from pyperclip.paste() and extract URL
  - If clipboard also fails, returns None
"""

import re
import io
import os
from urllib.parse import urlparse

from PIL import Image

# ──────────────────────────────────────────────
# URL Regex Pattern
# ──────────────────────────────────────────────

# Matches http://, https://, www. domains, and bare domains like example.com/path
URL_REGEX = re.compile(
    r"(?:https?://|www\.)[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)+(?:/[^\s()<>\"']*)?"
    r"|"
    r"(?<![a-zA-Z0-9@])[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"\.[a-zA-Z]{2,}(?:/[^\s()<>\"']*)?(?![a-zA-Z0-9])",
    re.IGNORECASE,
)


# ──────────────────────────────────────────────
# 1. Screen Capture
# ──────────────────────────────────────────────

def capture_screen(monitor_index=1):
    """
    Capture the specified monitor (default: primary monitor) as a PIL Image.

    Args:
        monitor_index: 1-based monitor index. 1 = primary monitor.

    Returns:
        PIL.Image: The captured screenshot, or None on failure.
    """
    try:
        import mss
    except ImportError:
        print("   ⚠️  mss not installed. Cannot capture screen.")
        return None

    try:
        with mss.mss() as sct:
            # Get monitor info
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 1  # fallback to primary

            monitor = monitors[monitor_index]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            return img
    except Exception as e:
        print(f"   ⚠️  Screen capture failed: {e}")
        return None


# ──────────────────────────────────────────────
# 2. OCR Text Extraction
# ──────────────────────────────────────────────

# Lazy-loaded EasyOCR reader (initialized once)
_ocr_reader = None


def _get_ocr_reader():
    """Get or initialize the EasyOCR reader singleton."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            print("   🔍 Initializing EasyOCR (first load may take a moment)...")
            _ocr_reader = easyocr.Reader(
                ["en"],
                gpu=False,  # Use CPU to avoid CUDA dependency issues
            )
        except ImportError:
            print("   ⚠️  EasyOCR not installed. OCR unavailable.")
            return None
        except Exception as e:
            print(f"   ⚠️  EasyOCR initialization failed: {e}")
            return None
    return _ocr_reader


def extract_text_from_image(image):
    """
    Run OCR on a PIL Image and return all detected text.

    Args:
        image: PIL.Image object to analyze.

    Returns:
        str: All detected text concatenated, or empty string on failure.
    """
    reader = _get_ocr_reader()
    if reader is None:
        return ""

    try:
        # Save image to a temporary bytes buffer for EasyOCR
        with io.BytesIO() as buf:
            image.save(buf, format="PNG")
            buf.seek(0)
            results = reader.readtext(buf.getvalue(), paragraph=True)

        # Concatenate all detected text
        texts = [result[1] for result in results]
        return " ".join(texts)
    except Exception as e:
        print(f"   ⚠️  OCR extraction failed: {e}")
        return ""


# ──────────────────────────────────────────────
# 3. URL Extraction from Text
# ──────────────────────────────────────────────

def extract_urls_from_text(text):
    """
    Extract all valid-looking URLs from a text string using regex.

    Args:
        text: The text to search for URLs.

    Returns:
        list: A list of normalized URL strings found in the text.
    """
    if not text:
        return []

    matches = URL_REGEX.findall(text)
    urls = []

    for match in matches:
        url = match.strip().rstrip(".,;:!?)")

        # Normalize: prepend https:// if missing
        if url.startswith("www."):
            url = f"https://{url}"
        elif not url.startswith(("http://", "https://")):
            # It's a bare domain like "example.com"
            url = f"https://{url}"

        # Validate basic URL structure
        parsed = urlparse(url)
        if parsed.netloc and "." in parsed.netloc:
            urls.append(url)

    return urls


# ──────────────────────────────────────────────
# 4. Clipboard URL Extraction
# ──────────────────────────────────────────────

def get_url_from_clipboard():
    """
    Extract URL from system clipboard text.

    Returns:
        str: The first valid URL found in clipboard, or None.
    """
    try:
        import pyperclip
        text = pyperclip.paste()
        if text and text.strip():
            urls = extract_urls_from_text(text.strip())
            if urls:
                return urls[0]
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────
# 5. Main Function: get_active_url()
# ──────────────────────────────────────────────

def get_active_url():
    """
    Capture the user's primary monitor using OCR and extract any visible URL.
    If no URL is found on screen, immediately check the clipboard.

    This is the main entry point for Zyra's link analysis feature.

    Returns:
        str: The extracted URL string, or None if no URL found.
    """
    # Step 1: Try to capture URL from screen via OCR
    print("\n📸 Capturing screen for URL detection...")

    image = capture_screen()
    if image is not None:
        print(f"   ✅ Screen captured ({image.size[0]}x{image.size[1]}px)")

        text = extract_text_from_image(image)
        if text:
            print(f"   📝 OCR detected text ({len(text)} chars)")
            urls = extract_urls_from_text(text)
            if urls:
                url = urls[0]
                print(f"   🔗 URL found on screen: {url}")
                if len(urls) > 1:
                    print(f"   ℹ️  Found {len(urls)} URLs total, using first one.")
                return url
        else:
            print("   ❌ No text detected on screen.")
    else:
        print("   ❌ Screen capture failed.")

    # Step 2: Fallback to clipboard
    print("   📋 Checking clipboard for URL...")
    url = get_url_from_clipboard()
    if url:
        print(f"   ✅ URL found in clipboard: {url}")
        return url

    # Step 3: No URL found anywhere
    print("   ❌ No URL found on screen or in clipboard.")
    return None


# Alias for backward compatibility
get_url_smart = get_active_url


# ──────────────────────────────────────────────
# 6. Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Zyra Screen OCR — Standalone Test")
    print("=" * 50)
    print()

    # Test URL extraction from sample text
    print("--- Testing URL regex extraction ---")
    test_texts = [
        "Check out https://www.google.com for more info",
        "Visit bit.ly/3xM7abc for the deal",
        "Here is the link: example.com/login",
        "No URLs here at all",
        "Multiple: https://safe.com and http://evil.tk/login",
    ]

    for text in test_texts:
        urls = extract_urls_from_text(text)
        if urls:
            print(f"  📝 \"{text[:50]}...\"")
            for u in urls:
                print(f"     → {u}")
        else:
            print(f"  📝 \"{text}\"")
            print(f"     → No URLs found")
    print()

    # Test get_active_url() - the main function
    print("--- Testing get_active_url() ---")
    print("(Will capture screen, then fallback to clipboard...)")
    url = get_active_url()
    if url:
        print(f"\n  ✅ URL found: {url}")
    else:
        print("\n  ℹ️  No URL found on screen or clipboard (this is normal if no links are visible).")
    print()

    print("=" * 50)
    print("  Test complete.")
    print("=" * 50)
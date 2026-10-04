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
import threading
import time
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
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)+"
    r"(?:/[^\s()<>\"']*)?(?![a-zA-Z0-9])",
    re.IGNORECASE,
)


# ──────────────────────────────────────────────
# OCR tuning (keeps screen capture responsive)
# ──────────────────────────────────────────────

# Wider screenshots are scaled down before OCR — cost scales with pixel count
# and URLs stay legible, so this cuts the capture time on high-res displays.
MAX_OCR_WIDTH = 1000
# Hard cap for a single OCR pass — the capture never blocks forever. Generous
# enough to finish on a CPU-only machine (a full-screen EasyOCR pass is slow).
OCR_TIMEOUT_SECONDS = 45

# Plausible top-level domains for BARE domains. Screen/clipboard text has no
# scheme, so a loose match would otherwise pick up code identifiers such as
# 'fastapi.testclient' or filenames such as 'torch.dataloader'. Only accept a
# bare match when its final label is a real-ish TLD.
_COMMON_TLDS = {
    "com", "net", "org", "edu", "gov", "mil", "int", "io", "co", "ai", "app",
    "dev", "me", "tv", "info", "biz", "online", "site", "store", "shop", "club",
    "xyz", "top", "live", "news", "link", "click", "ly", "cc", "pw", "tk", "ml",
    "ga", "cf", "gq", "win", "bid", "loan", "work", "date", "icu", "cam", "rest",
    "monster", "quest", "vip", "fun", "space", "website", "press", "cloud",
    "tech", "digital", "agency", "solutions", "media", "blog", "page", "run",
    "sh", "gg", "to", "ws", "fm", "am", "gl", "gd", "vc", "so",
    "us", "uk", "ca", "au", "in", "de", "fr", "jp", "cn", "ru", "br", "nl", "it",
    "es", "se", "no", "be", "ch", "at", "dk", "fi", "pl", "gr", "pt", "cz", "ie",
    "nz", "za", "sg", "hk", "kr", "mx",
}


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


import zyra_paths


def _get_ocr_reader():
    """Get or initialize the EasyOCR reader singleton."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            print("   🔍 Initializing EasyOCR (first load may take a moment)...")
            # Optional OCR weights are read-only; honour the frozen bundle first
            # and only then download to the user's profile cache.
            model_storage_directory = None
            _bundled = zyra_paths.resource_path("easyocr", "model")
            if os.path.isdir(_bundled):
                model_storage_directory = _bundled
            _ocr_reader = easyocr.Reader(
                ["en"],
                gpu=False,  # Use CPU to avoid CUDA dependency issues
                model_storage_directory=model_storage_directory,
            )
        except ImportError:
            print("   ⚠️  EasyOCR not installed. OCR unavailable.")
            return None
        except Exception as e:
            print(f"   ⚠️  EasyOCR initialization failed: {e}")
            return None
    return _ocr_reader


def warm_up_ocr():
    """
    Pre-load the EasyOCR reader (and its models) so the first real capture is
    fast instead of paying a one-off cold-start cost. Best effort, never raises.
    """
    try:
        return _get_ocr_reader() is not None
    except Exception:
        return False


def _readtext_bounded(reader, image_bytes, timeout=OCR_TIMEOUT_SECONDS):
    """
    Run EasyOCR in a worker thread and return a list of strings, or None if the
    OCR pass exceeded the timeout (so a capture can never hang forever).
    """
    box = {}

    def _run():
        try:
            box["result"] = reader.readtext(image_bytes, detail=0, paragraph=True)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return None
    if "error" in box:
        raise box["error"]
    return box.get("result", [])


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

    # Downscale large screenshots — OCR cost scales with pixel count and URLs
    # stay legible, so this keeps the capture fast on high-res displays.
    try:
        width, height = image.size
        if width > MAX_OCR_WIDTH:
            scale = MAX_OCR_WIDTH / float(width)
            image = image.resize((int(width * scale), int(height * scale)))
    except Exception:
        pass

    started = time.monotonic()
    try:
        # Save image to a temporary bytes buffer for EasyOCR
        with io.BytesIO() as buf:
            image.save(buf, format="PNG")
            data = buf.getvalue()

        results = _readtext_bounded(reader, data)
        if results is None:
            print(f"   ⚠️  OCR timed out after {OCR_TIMEOUT_SECONDS}s.")
            return ""

        # Concatenate all detected text (detail=0 -> list of strings).
        text = " ".join(str(item) for item in results)
        print(f"   ⏱️  OCR completed in {time.monotonic() - started:.1f}s")
        return text
    except Exception as e:
        print(f"   ⚠️  OCR extraction failed: {e}")
        return ""


# ──────────────────────────────────────────────
# 3. URL Extraction from Text
# ──────────────────────────────────────────────

def extract_urls_from_text(text):
    """
    Extract valid-looking URLs from a text string, best candidates first.

    Explicit ``http(s)://`` and ``www.`` links are returned before bare
    domains, and a bare domain is only accepted when its final label is a
    plausible TLD — so code identifiers / filenames (e.g. 'fastapi.testclient',
    'torch.dataloader') are not mistaken for links.

    Args:
        text: The text to search for URLs.

    Returns:
        list: Normalized URL strings found in the text (best first).
    """
    if not text:
        return []

    matches = URL_REGEX.findall(text)
    prioritized = []   # http(s):// or www. links
    bare = []          # scheme-less domain.tld links
    seen = set()

    for match in matches:
        url = match.strip().rstrip(".,;:!?)")
        if not url or url in seen:
            continue

        lowered = url.lower()
        if lowered.startswith(("http://", "https://")):
            normalized = url
            bucket = prioritized
        elif lowered.startswith("www."):
            normalized = f"https://{url}"
            bucket = prioritized
        else:
            # Bare domain — require a plausible TLD to avoid false positives.
            tld = lowered.rsplit(".", 1)[-1].split("/", 1)[0]
            if tld not in _COMMON_TLDS:
                continue
            normalized = f"https://{url}"
            bucket = bare

        parsed = urlparse(normalized)
        if not (parsed.netloc and "." in parsed.netloc):
            continue

        seen.add(url)
        bucket.append(normalized)

    return prioritized + bare


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

def _clipboard_exact_url():
    """
    Return the clipboard URL only when the clipboard holds *just* a URL.

    This is the fast path: copying a link is the most common way users hand
    Zyra a URL, and it resolves instantly without any screen OCR. When the
    clipboard contains prose (not a bare link) this returns None so the
    on-screen link is used instead.
    """
    try:
        import pyperclip
        text = (pyperclip.paste() or "").strip()
    except Exception:
        return None

    if not text or len(text) > 2048 or any(ch.isspace() for ch in text):
        return None

    candidate = text if text.startswith(("http://", "https://")) else f"https://{text}"
    parsed = urlparse(candidate)
    if parsed.netloc and "." in parsed.netloc:
        return candidate
    return None


def get_active_url():
    """
    Resolve the link the user is looking at.

    Order of resolution:
      1. Clipboard holding exactly one URL  → instant (fast path)
      2. On-screen URL via OCR (downscaled + bounded)
      3. Any URL inside clipboard text      → fallback

    This is the main entry point for Zyra's link analysis feature.

    Returns:
        str: The extracted URL string, or None if no URL found.
    """
    # Fast path: the clipboard is a single URL -> no OCR needed.
    url = _clipboard_exact_url()
    if url:
        print(f"   ✅ URL found in clipboard (fast path): {url}")
        return url

    # Step 1: capture the on-screen URL via OCR (bounded).
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

    # Step 3: fall back to any URL inside clipboard text.
    print("   📋 Checking clipboard for URL...")
    url = get_url_from_clipboard()
    if url:
        print(f"   ✅ URL found in clipboard: {url}")
        return url

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
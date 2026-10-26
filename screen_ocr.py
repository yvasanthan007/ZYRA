"""Screen capture via MSS and safe OCR URL extraction."""
import re
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from PIL import Image
URL_REGEX = re.compile(r"(?:https?://|www\.)[^\s()<>\"']+|(?<![A-Za-z0-9@])[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?:/[^\s()<>\"']*)?", re.I)
_COMMON_TLDS = {"com", "net", "org", "edu", "gov", "mil", "int", "io", "co", "ai", "app", "dev", "me", "tv", "info", "biz", "online", "site", "store", "shop", "club", "xyz", "top", "live", "news", "link", "click", "ly", "cc", "pw", "tk", "ml", "ga", "cf", "gq", "win", "bid", "loan", "work", "date", "icu", "cam", "rest", "monster", "quest", "vip", "fun", "space", "website", "press", "cloud", "tech", "digital", "agency", "solutions", "media", "blog", "page", "run", "sh", "gg", "to", "ws", "fm", "am", "gl", "gd", "vc", "so", "us", "uk", "ca", "au", "in", "de", "fr", "jp", "cn", "ru", "br", "nl", "it", "es", "se", "no", "be", "ch", "at", "dk", "fi", "pl", "gr", "pt", "cz", "ie", "nz", "za", "sg", "hk", "kr", "mx"}
_ocr_reader = None
_ocr_reader_lock = threading.Lock()


def _normalize_extracted_url(value):
    """Normalize a URL candidate without resolving or visiting it."""
    value = (value or "").strip().strip("<>{}[]\"'").rstrip(".,;:!?)")
    if not value:
        return None
    if value.lower().startswith("www."):
        value = "https://" + value
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
        if parts.scheme.lower() not in ("http", "https") or not host:
            return None
        ascii_host = host.encode("idna").decode("ascii").lower()
        if "." not in ascii_host and not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ascii_host):
            return None
        if any(ch.isspace() or ord(ch) < 32 for ch in value):
            return None
        if "@" in parts.netloc and not all(parts.netloc.rpartition("@")[::2]):
            return None
        userinfo = parts.netloc.rpartition("@")[0] + "@" if "@" in parts.netloc else ""
        netloc = userinfo + ascii_host + (f":{port}" if port is not None else "")
        return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))
    except (UnicodeError, ValueError):
        return None

def _repair_ocr_url_noise(text):
    """Repair common OCR punctuation errors in links."""
    text = re.sub(r"\b[hf]lt?t?ps?\s*[:;]?\s*[Il1/\\|]{1,}", "https://", text, flags=re.I)
    text = re.sub(r"\bhttps?\s*[:;]?\s*[Il1/\\|]{1,}", "https://", text, flags=re.I)
    text = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", text)
    return re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", text)


def extract_urls_from_text(text):
    """Extract, normalize, validate and de-duplicate URLs from untrusted text."""
    if not isinstance(text, str) or not text:
        return []
    repaired = _repair_ocr_url_noise(text)
    results, seen = [], set()
    for match in URL_REGEX.finditer(repaired):
        value = match.group(0).rstrip(".,;:!?)")
        normalized = _normalize_extracted_url(value)
        if not normalized:
            continue
        # Unanchored dotted identifiers are common in code and log text. Only
        # accept unknown TLDs when the match had an explicit URL/www prefix.
        explicit = value.lower().startswith(("http://", "https://", "www."))
        host = urlsplit(normalized).hostname or ""
        tld = host.rsplit(".", 1)[-1].lower()
        if not explicit and tld not in _COMMON_TLDS:
            continue
        if "." not in host and not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
            continue
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            results.append(normalized)
    return results

def _get_ocr_reader():
    """Load and cache a single EasyOCR reader."""
    global _ocr_reader
    if _ocr_reader is None:
        with _ocr_reader_lock:
            if _ocr_reader is None:
                import easyocr
                _ocr_reader = easyocr.Reader(["en"], gpu=False)
    return _ocr_reader

def capture_screen(monitor_index=1):
    """Capture a monitor using MSS, returning None on failure."""
    try:
        import mss
        with mss.mss() as sct:
            index = monitor_index if 0 < monitor_index < len(sct.monitors) else 1
            shot = sct.grab(sct.monitors[index])
            return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        return None

def capture_screens():
    """Capture all physical displays using MSS."""
    try:
        import mss
        with mss.mss() as sct:
            return [Image.frombytes("RGB", shot.size, shot.rgb)
                    for shot in (sct.grab(m) for m in sct.monitors[1:])]
    except Exception:
        image = capture_screen()
        return [image] if image is not None else []


def extract_text_from_image(image):
    """OCR an image through the cached EasyOCR model."""
    if image is None:
        return ""
    try:
        return "\n".join(map(str, _get_ocr_reader().readtext(image, detail=0, paragraph=True)))
    except Exception:
        return ""


def extract_urls_from_image(image):
    return extract_urls_from_text(extract_text_from_image(image))


def get_url_from_clipboard():
    """Return the first normalized clipboard URL; never log clipboard text."""
    try:
        import pyperclip
        urls = extract_urls_from_text(pyperclip.paste() or "")
        return urls[0] if urls else None
    except Exception:
        return None

def _clipboard_exact_urls():
    """Read clipboard only when it consists of one URL-like token."""
    try:
        import pyperclip
        text = (pyperclip.paste() or "").strip()
        if not text or len(text) > 2048 or any(ch.isspace() for ch in text):
            return []
        return extract_urls_from_text(text)
    except Exception:
        return []


def _clipboard_exact_url():
    urls = _clipboard_exact_urls()
    return urls[0] if urls else None

def _get_active_browser_url():
    """Read the foreground browser address bar, restoring clipboard contents."""
    if sys.platform != "win32":
        return None
    try:
        import pyautogui
        import pyperclip
        import win32gui
        title = (win32gui.GetWindowText(win32gui.GetForegroundWindow()) or "").lower()
        if not any(marker in title for marker in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")):
            return None
        previous = pyperclip.paste()
        try:
            pyautogui.hotkey("ctrl", "l")
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.15)
            copied = pyperclip.paste() or ""
        finally:
            pyperclip.copy(previous or "")
        urls = extract_urls_from_text(copied)
        return urls[0] if len(urls) == 1 else None
    except Exception:
        return None

def get_active_url():
    """Prefer an explicit clipboard link, otherwise scan current displays."""
    urls = _clipboard_exact_urls()
    if urls:
        return urls[0]
    for image in capture_screens():
        urls = extract_urls_from_image(image)
        if urls:
            return urls[0]
    return _get_active_browser_url() or get_url_from_clipboard()


def _capture_url_isolated(timeout=90):
    """Backward-compatible capture entry point."""
    return get_active_url()

get_url_smart = get_active_url

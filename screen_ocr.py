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
                from pathlib import Path
                # PyInstaller bundles the cached weights under easyocr/model;
                # tell EasyOCR where they are so packaged builds can run offline.
                bundle_root = getattr(sys, "_MEIPASS", None)
                model_storage_directory = (
                    str(Path(bundle_root) / "easyocr" / "model")
                    if bundle_root else None
                )
                options = {"gpu": False, "verbose": False}
                if model_storage_directory and Path(model_storage_directory).is_dir():
                    options["model_storage_directory"] = model_storage_directory
                _ocr_reader = easyocr.Reader(["en"], **options)
    return _ocr_reader

def warm_up_ocr():
    """Load EasyOCR once in the background during application startup."""
    return _get_ocr_reader()


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
    """Extract the displayed browser URL, preferring its address bar strip."""
    if image is None:
        return []
    width, height = getattr(image, "size", (0, 0))
    if width > 0 and height > 0:
        # The URL in the browser chrome is the intended target; scanning page
        # text first can accidentally select an ad, footer, or unrelated link.
        try:
            address_bar = image.crop((0, 0, width, min(height, max(80, int(height * 0.24)))))
            urls = extract_urls_from_text(extract_text_from_image(address_bar))
            if urls:
                return urls
        except Exception:
            pass
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
    # Browser address-bar capture avoids incidental URLs in other windows.
    browser_url = _get_active_browser_url()
    if browser_url:
        return browser_url
    for image in capture_screens():
        urls = extract_urls_from_image(image)
        if urls:
            return urls[0]
    return _clipboard_exact_url() or get_url_from_clipboard()


def _capture_url_isolated(timeout=90):
    """Backward-compatible capture entry point."""
    return get_active_url()

get_url_smart = get_active_url



# EasyOCR accepts image paths, bytes, or numpy arrays, not PIL.Image objects.
# MSS returns PIL images, so convert both screen captures and address-bar crops.
def extract_text_from_image(image):
    # OCR a PIL image through the cached EasyOCR model.
    if image is None:
        return ""
    try:
        import numpy as np
        pixels = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
        return "\n".join(map(str, _get_ocr_reader().readtext(
            pixels, detail=0, paragraph=True)))
    except Exception as exc:
        # Don't log recognized text, which may contain sensitive on-screen data.
        print(f"[OCR] screen text extraction failed ({type(exc).__name__}): {exc}")
        return ""

# Re-define extraction with an EasyOCR-compatible pixel-array input. The
# earlier implementation passes a PIL Image directly, which EasyOCR rejects.
def extract_text_from_image(image):
    # OCR an MSS/PIL image through EasyOCR's supported NumPy input.
    if image is None:
        return ""
    try:
        import numpy as np
        pixels = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
        return "\n".join(map(str, _get_ocr_reader().readtext(
            pixels, detail=0, paragraph=True)))
    except Exception as exc:
        print(f"[OCR] screen text extraction failed ({type(exc).__name__}): {exc}")
        return ""


# Screen capture candidate resolver (foreground browser > OCR > clipboard).
def get_active_url():
    browser_url = _get_active_browser_url()
    if browser_url:
        return browser_url
    for image in capture_screens():
        urls = extract_urls_from_image(image)
        if urls:
            return urls[0]
    return _clipboard_exact_url() or get_url_from_clipboard()


def _repair_explicit_ocr_url_whitespace(text):
    # Recover URLs even when OCR mistakes punctuation for letters and splits
    # host/path tokens (for example https:Ilsecure-login example xyzlaccount).
    text = re.sub(r"(?i)https\s*[:;]?\s*[Il1/\\|]{1,}", "https://", text)
    text = re.sub(r"(?i)http\s*[:;]?\s*[Il1/\\|]{1,}", "http://", text)
    text = re.sub(r"(?i)https://(?=[A-Za-z0-9-])", "https://", text)
    # For each explicit scheme, consider the next contiguous OCR token run and
    # compact separators/spaces there only; stop at a distinct sentence phrase.
    def repair_candidate(match):
        candidate = match.group(0)
        candidate = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", candidate)
        candidate = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", candidate)
        candidate = re.sub(r"(?<=\w)\s+(?=[A-Za-z0-9-]+\.)", ".", candidate)
        candidate = re.sub(r"(?<=\.)\s+(?=[A-Za-z0-9-]+(?:\.|/|\b))", ".", candidate)
        candidate = re.sub(r"(?<=\w)\s+(?=[A-Za-z0-9-]+/)", "", candidate)
        candidate = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[A-Za-z0-9-]+(?:/|\.|\b))", "", candidate)
        return candidate
    return re.sub(r"(?i)https://[^\n<>\"']{0,160}", repair_candidate, text)

_base_extract_urls_from_text = extract_urls_from_text
def extract_urls_from_text(text):
    # Extract candidates after conservative OCR token repairs.
    if not isinstance(text, str) or not text:
        return []
    repaired = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    repaired = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", repaired)
    repaired = _repair_explicit_ocr_url_whitespace(repaired)
    repaired = re.sub(r"(?i)http(?=[Il1/\\|])", "http://", repaired)
    # Recover OCR's common vertical-bar/uppercase-I scheme and slash errors.
    repaired = re.sub(r"(?i)https\s*[:;]?\s*[Il1/\\|]{1,}", "https://", repaired)
    repaired = re.sub(r"(?i)http\s*[:;]?\s*[Il1/\\|]{1,}", "http://", repaired)
    repaired = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", repaired)
    repaired = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", repaired)
    repaired = re.sub(r"(?<=\w)\s+(?=[A-Za-z0-9-]+\.)", ".", repaired)
    repaired = re.sub(r"(?<=\w)\s+(?=[A-Za-z0-9-]+(?=\s|/|$))", ".", repaired)
    repaired = re.sub(r"(?<=\.)\s+(?=[A-Za-z0-9-]+(?:\.|/|\b))", ".", repaired)
    repaired = re.sub(r"(?<=\w)\s+(?=[A-Za-z0-9-]+/)", "", repaired)
    # OCR frequently renders the slash following a scheme as lowercase L or I.
    repaired = re.sub(r"(?i)https://(?=[A-Za-z0-9-])", "https://", repaired)
    return _base_extract_urls_from_text(repaired)


# Final narrow OCR repair: missing host dots and scheme separator OCR noise.
def _extract_urls_from_text_with_host_repair(text):
    if not isinstance(text, str) or not text:
        return []
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    value = re.sub(r"(?i)(https?://)I(?=[A-Za-z0-9-])", r"\1", value)
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+\s+[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})?)(?=[/\s]|$)", r"\1.\2", value)
    value = re.sub(r"(?i)(https?://[^/\s.]+)-([A-Za-z0-9-]+)\s+([A-Za-z]{2,}(?:\s+[A-Za-z]{2,})?)(?=[/\s]|$)", r"\1-\2.\3", value)
    # Recover the common host-vs-TLD split while preserving path text.
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+-[A-Za-z0-9-]+)\s+([A-Za-z]{2,})(?=/|\s|$)", r"\1.\2", value)
    # Insert dots where OCR separated conventional domain labels with spaces.
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+\s+[A-Za-z]{2,})(?=[/\s]|$)", r"\1.\2", value)
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+\.[A-Za-z0-9-]+)\s+([A-Za-z]{2,})(?=[/\s]|$)", r"\1.\2", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    value = re.sub(r"(?i)(https?://[^\s<>\"']+)l(?=[A-Za-z0-9_-]+(?:\b|$))", r"\1/", value)
    value = re.sub(r"(?i)(https?://[^\s<>\"']+)l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    return _base_extract_urls_from_text(value)

extract_urls_from_text = _extract_urls_from_text_with_host_repair


# Restore known URL punctuation variants only inside URL-shaped text.
def _repair_ocr_url_noise(text):
    text = re.sub(r"(?i)https\s*[:;]?\s*[Il1/\\|]{1,}", "https://", text)
    text = re.sub(r"(?i)http\s*[:;]?\s*[Il1/\\|]{1,}", "http://", text)
    text = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", text)
    text = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", text)
    return text

def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = _repair_ocr_url_noise(text)
    value = re.sub(r"(?i)(https?://)I(?=[A-Za-z0-9-])", r"\1", value)
    # Correct an OCR-created space between hostname labels only when a known
    # public suffix follows; preserve explicit hyphenated labels and path.
    suffixes = "com|net|org|edu|gov|io|co|ai|app|dev|me|info|biz|online|site|store|shop|xyz|top|live|news|link|click|cc|pw|win|loan|work|date|icu|cam|rest|monster|quest|vip|fun|space|website|cloud|tech|uk|ca|au|in|de|fr|jp|cn|ru|br|nl|it|es|se|no|be|ch|at|dk|fi|pl|gr|pt|ie|nz|za|sg|hk|kr|mx"
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)\s+({suffixes})(?=/|\b)", r"\1.\2", value)
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)\s+(" + suffixes + r")(?=/|\b)", r"\1.\2.\3", value)
    # OCR commonly reads a trailing path separator as lowercase l; repair
    # only when an authority already ends in a known suffix and no slash exists.
    value = re.sub(r"(?i)(https?://[^\s/]+\.(?:" + suffixes + r"))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    return _base_extract_urls_from_text(value)


def extract_urls_from_text(text):
    # Parse OCR text while tolerating known split/blur errors.
    if not isinstance(text, str) or not text:
        return []
    value = text
    # Repair scheme OCR, including https:Il and https:/I variants.
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", value)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    value = re.sub(r"(?i)https?\s*:\s*//", lambda m: "https://" if m.group(0).lower().startswith("https") else "http://", value)
    # Dots separated by OCR spacing are unambiguous domain separators.
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    suffixes = sorted(_COMMON_TLDS, key=len, reverse=True)
    suffix_pattern = "|".join(re.escape(item) for item in suffixes)
    # Insert the dot before a recognized public suffix when OCR omitted it.
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+({suffix_pattern})(?=/|\b)", r"\1.\2", value)
    # If host label and multi-part suffix were spaced, restore both dots.
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)\s+({suffix_pattern})(?=/|\b)", r"\1.\2.\3", value)
    # EasyOCR frequently sees slash as lowercase l immediately after a URL host.
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+\.(?:{suffix_pattern}))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    return _base_extract_urls_from_text(value)


# Keep the OCR-token parser deterministic; discard superseded experimental
# repair wrappers above rather than chaining multiple lossy transformations.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = text
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", value)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    suffixes = "|".join(re.escape(item) for item in sorted(_COMMON_TLDS, key=len, reverse=True))
    # Only reconstruct omitted dots immediately before a known public suffix.
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+({suffixes})(?=/|\b)", r"\1.\2", value)
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)\s+({suffixes})(?=/|\b)", r"\1.\2.\3", value)
    # Recognize OCR's lowercase-l substitution for the slash after a known TLD.
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+\.(?:{suffixes}))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    return _base_extract_urls_from_text(value)


# Final URL parser for EasyOCR's often space-delimited output.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = text
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", value)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    suffix = "|".join(re.escape(t) for t in sorted(_COMMON_TLDS, key=len, reverse=True))
    # Rejoin spaced labels only as a host when a known TLD follows; preserve
    # existing hyphens and restore the missing path slash if OCR reads it as l.
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+([A-Za-z0-9-]+)\s+({suffix})(?=l|/|\b)", r"\1.\2.\3", value)
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+({suffix})(?=l|/|\b)", r"\1.\2", value)
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+\.(?:{suffix}))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    return _base_extract_urls_from_text(value)


# Last extractor wrapper: if unambiguous explicit OCR text already contains a
# complete URL, retain its original tokens rather than joining unrelated labels.
_previous_url_extractor = extract_urls_from_text
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    # Preserve URLs that already match the standard parser; repairs are only
    # considered when OCR spacing or punctuation prevented any direct match.
    direct = _base_extract_urls_from_text(_repair_ocr_url_noise(text))
    if direct:
        return direct
    return _previous_url_extractor(text)


# Prefer explicit scheme-anchored tokens with their full path before the
# permissive domain-only parser, which can otherwise start at a path label.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    repaired = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    repaired = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", repaired)
    repaired = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", repaired)
    repaired = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", repaired)
    explicit = re.findall(r"(?i)https?://[^\s()<>\"']+", repaired)
    results = []
    for candidate in explicit:
        candidate = candidate.rstrip(".,;:!?)")
        urls = _base_extract_urls_from_text(candidate)
        results.extend(urls)
    if results:
        return list(dict.fromkeys(results))
    return _previous_url_extractor(text)


# When an explicit scheme is present but the first host token is incomplete,
# rejoin OCR-spaced host labels before the first known public suffix.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    suffix = "|".join(re.escape(t) for t in sorted(_COMMON_TLDS, key=len, reverse=True))
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+(?:-[A-Za-z0-9-]+)?)\s+([A-Za-z0-9-]+)\s+({suffix})(?=/|\b)", r"\1.\2.\3", value)
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)\s+({suffix})(?=/|\b)", r"\1.\2", value)
    # Re-evaluate explicit URL tokens as a complete candidate, preserving path.
    candidates = re.findall(r"(?i)https?://[^\s()<>\"']+", value)
    output = []
    for candidate in candidates:
        candidate = candidate.rstrip(".,;:!?)")
        normalized = _normalize_extracted_url(candidate)
        if normalized and normalized not in output:
            output.append(normalized)
    if output:
        return output
    return _base_extract_urls_from_text(value)


# Preserve original TLD token when OCR inserted spaces before it; avoid the
# legacy URL regex's aggressive OCR repair on the reconstructed candidate.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    suffix = "|".join(re.escape(t) for t in sorted(_COMMON_TLDS, key=len, reverse=True))
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+(?:-[A-Za-z0-9-]+)*)\s+([A-Za-z0-9-]+)\s+({suffix})(?=l|/|\b)", r"\1.\2.\3", value)
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+({suffix})(?=l|/|\b)", r"\1.\2", value)
    # An OCR 'l' after a known TLD is a path separator; retain the remaining
    # letters instead of running broad character substitution over the host.
    value = re.sub(rf"(?i)(https?://[^\s/]+\.(?:{suffix}))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    found = []
    for token in re.findall(r"(?i)https?://[^\s()<>\"']+", value):
        token = token.rstrip(".,;:!?)")
        normalized = _normalize_extracted_url(token)
        if normalized and normalized not in found:
            found.append(normalized)
    if found:
        return found
    return _base_extract_urls_from_text(value)


# Fix the OCR output seen from EasyOCR on browser address bars:
# "https:Ilsecure-login example xyzlaccount" -> https://secure-login.example.xyz/account
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    # For OCR-lost dots, only split the final hostname labels when a known
    # public suffix is present. The leading labels remain verbatim.
    suffix = "|".join(re.escape(t) for t in sorted(_COMMON_TLDS, key=len, reverse=True))
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)\s+({suffix})(?=l|/|\b)", r"\1.\2.\3", value)
    value = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+({suffix})(?=l|/|\b)", r"\1.\2", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    value = re.sub(rf"(?i)(https?://[^\s/]+\.(?:{suffix}))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    results = []
    for candidate in re.findall(r"(?i)https?://[^\s()<>\"']+", value):
        candidate = candidate.rstrip(".,;:!?)")
        normalized = _normalize_extracted_url(candidate)
        if normalized and normalized not in results:
            results.append(normalized)
    return results if results else _base_extract_urls_from_text(value)


# Do not let the generic unanchored URL regex reinterpret a failed explicit URL
# as a URL beginning in its path. A scheme requires a valid authority.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    repaired = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    repaired = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", repaired)
    suffixes = "|".join(re.escape(t) for t in sorted(_COMMON_TLDS, key=len, reverse=True))
    repaired = re.sub(rf"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)\s+({suffixes})(?=l|/|\b)", r"\1.\2.\3", repaired)
    repaired = re.sub(rf"(?i)(https?://[A-Za-z0-9.-]+)\s+({suffixes})(?=l|/|\b)", r"\1.\2", repaired)
    repaired = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", repaired)
    repaired = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", repaired)
    repaired = re.sub(rf"(?i)(https?://[^\s/]+\.(?:{suffixes}))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", repaired)
    matches = re.findall(r"(?i)https?://[^\s()<>\"']+", repaired)
    if matches:
        output = []
        for match in matches:
            normalized = _normalize_extracted_url(match.rstrip(".,;:!?)"))
            if normalized and normalized not in output:
                output.append(normalized)
        return output
    # Only unanchored OCR text (no visible scheme) uses broad URL discovery.
    return _base_extract_urls_from_text(repaired)


# Replace OCR spaced-host reconstruction with a domain-aware parser that
# preserves the initial hyphenated label and reattaches the next hostname label.
def extract_urls_from_text(text):
    if not isinstance(text, str) or not text:
        return []
    value = re.sub(r"(?i)https\s*:\s*[Il1/\\|]+", "https://", text)
    value = re.sub(r"(?i)http\s*:\s*[Il1/\\|]+", "http://", value)
    # Join spaced hostname labels and insert the domain dots; this recognizes
    # EasyOCR output such as "https://paypa1-login verify-account-now.xyz/login".
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+-[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+\.[A-Za-z]{2,})(?=/|\b)", r"\1.\2", value)
    value = re.sub(r"(?i)(https?://[A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)\s+([A-Za-z]{2,})(?=/|\b)", r"\1.\2.\3", value)
    value = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", value)
    value = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", value)
    value = re.sub(r"(?i)(https?://[^\s/]+\.(?:" + "|".join(map(re.escape, _COMMON_TLDS)) + r"))l(?=[A-Za-z0-9_-]+(?:/|\b))", r"\1/", value)
    tokens = re.findall(r"(?i)https?://[^\s()<>\"']+", value)
    urls = []
    for token in tokens:
        normalized = _normalize_extracted_url(token.rstrip(".,;:!?)"))
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls if urls or tokens else _base_extract_urls_from_text(value)

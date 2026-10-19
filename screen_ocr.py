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
import sys
from urllib.parse import urlparse

from PIL import Image

# ── Windows console safety ──────────────────────────────────────────────
# Force UTF-8 output before any emoji status print below (📸 🔍 ⏱️ 📭 ✅ 🔗 …).
# On a cp1252 console a plain print() of these glyphs raises
# UnicodeEncodeError, which can abort the calling thread (and, in the voice
# path, the whole process). Matches the guard used in main.py / speak.py.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


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
# NOTE: keep this high enough that small address-bar/link text stays legible.
# EasyOCR misreads (and drops the '.' in) URLs once the text is downscaled too
# far — a 1000px cap turned "example.com/signin" into "example com/signin" and
# "paypa1-secure-login.xyz" into garbage, so screen links were never found.
# 1600px keeps dense URL text readable while still bounding the cost.
MAX_OCR_WIDTH = 1600
# Hard cap for a single OCR pass — the capture never blocks forever. Generous
# enough to finish on a CPU-only machine (a full-screen EasyOCR pass is slow:
# a warm reader does ~1600px in well under 15s, but a cold model + big screen
# can take longer, and abandoning it mid-inference just yields no URL).
OCR_TIMEOUT_SECONDS = int(os.environ.get("ZYRA_OCR_TIMEOUT_SECONDS", "90"))

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


def _is_plausible_tld(label: str) -> bool:
    # Accept known TLDs plus syntactically valid newer/country-code TLDs.
    label = (label or "").lower()
    return label in _COMMON_TLDS or bool(re.fullmatch(r"[a-z]{2,63}", label))


# ──────────────────────────────────────────────
# 1. Screen Capture
# ──────────────────────────────────────────────

def capture_screens():
    # Capture physical monitors separately rather than shrinking the virtual desktop.
    try:
        import mss
    except ImportError:
        print("   ⚠️  mss not installed. Cannot capture screen.")
        return []

    images = []
    try:
        with mss.mss() as sct:
            # Avoid shrinking multi-monitor screenshots until URL text is tiny.
            for monitor in sct.monitors[1:]:
                shot = sct.grab(monitor)
                images.append(Image.frombytes("RGB", shot.size, shot.rgb))
    except Exception as exc:
        print(f"   ⚠️  Multi-monitor screen capture failed: {exc}")
    return images

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
# Guards one-time reader construction so two concurrent captures can never
# build (and race on) two EasyOCR readers at once.
_ocr_reader_lock = threading.Lock()
# Serializes every reader.readtext() call. EasyOCR/torch is NOT thread-safe:
# two overlapping readtext() calls on the shared reader corrupt native state
# and can segfault the whole process. This lock is the crash guard.
_ocr_infer_lock = threading.Lock()


import zyra_paths


def _get_ocr_reader():
    """Get or initialize the EasyOCR reader singleton (thread-safe)."""
    global _ocr_reader
    if _ocr_reader is not None:
        return _ocr_reader
    with _ocr_reader_lock:
        # Double-checked: another thread may have built it while we waited.
        if _ocr_reader is not None:
            return _ocr_reader
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

    The actual readtext() runs under _ocr_infer_lock so only one inference is
    ever in flight on the shared, non-thread-safe reader — this is what keeps a
    timed-out (abandoned) worker from overlapping the next capture and
    segfaulting the process. The lock is acquired *inside* the worker so the
    timeout still bounds the caller; a capture that times out simply returns
    None and releases its claim as soon as the in-flight inference finishes.
    """
    box = {}

    def _run():
        # Serialize native inference; the timeout below still bounds the caller.
        with _ocr_infer_lock:
            try:
                box["result"] = reader.readtext(image_bytes, detail=0, paragraph=True)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        # Timed out. The worker keeps the infer lock only until its readtext
        # returns, then releases it — so the next capture waits for the current
        # inference instead of starting a second, crashing one.
        return None
    if "error" in box:
        raise box["error"]
    return box.get("result", [])


def extract_text_from_image(image):
    """
    Run OCR on a PIL Image and return all detected text.

    Uses the bounded worker wrapper so a capture can never block the event
    loop or hold the microphone open. Returns '' on OCR failure and logs a
    single diagnostic so the voice path can surface the reason to the user.
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
        # Save image to a temporary bytes buffer for EasyOCR.
        with io.BytesIO() as buf:
            image.save(buf, format="PNG")
            data = buf.getvalue()

        results = _readtext_bounded(reader, data, timeout=OCR_TIMEOUT_SECONDS)
        elapsed = time.monotonic() - started
        if results is None:
            print(f"   ⏱️  OCR timed out after {elapsed:.1f}s (bounded).")
            return ""
        # EasyOCR returns strings in detail=0 mode. Preserve line boundaries so
        # URL repair does not accidentally join neighboring UI labels.
        text = "\n".join(str(item) for item in results)
        print(f"   ⏱️  OCR completed in {elapsed:.1f}s")
        return text
    except Exception as e:
        print(f"   ⚠️  OCR extraction failed: {type(e).__name__}: {e}")
        return ""


def extract_urls_from_image(image):
    # Check browser chrome before page content: it identifies the active page,
    # unlike URLs mentioned in advertisements or page text.
    if image is None:
        return []
    width, height = image.size
    # Browser address bars sit at the top. OCR the full-width top strip first
    # so it can reliably identify the actual page URL before page-content links.
    # On kiosk/fullscreen windows without chrome, fall back to top and full frame.
    # Browser address bars sit in the top strip; searching a large 32% crop
    # first can pick an advert/article URL above the fold instead of the page
    # currently open. Prefer the address-bar band, then broaden as fallback for
    # kiosk/fullscreen windows whose chrome is hidden.
    address_height = max(1, min(height, int(height * 0.24)))
    address_text = extract_text_from_image(
        image.crop((0, 0, width, address_height)))
    address_urls = extract_urls_from_text(address_text) if address_text else []
    if address_urls:
        return address_urls
    top_height = max(address_height, min(height, int(height * 0.32)))
    top_text = extract_text_from_image(image.crop((0, 0, width, top_height)))
    top_urls = extract_urls_from_text(top_text) if top_text else []
    if top_urls:
        return top_urls
    full_text = extract_text_from_image(image)
    return extract_urls_from_text(full_text) if full_text else []


# ──────────────────────────────────────────────
# 3. URL Extraction from Text
# ──────────────────────────────────────────────

def _repair_ocr_url_noise(text: str) -> str:
    """Repair the punctuation EasyOCR mangles in on-screen URLs.

    Real EasyOCR output turns ``https://`` into ``https:Il`` / ``hltps:Il`` and,
    critically, **drops the dots between host labels** (``paypal com`` instead of
    ``paypal.com``), so a strict regex never matches a real screen link. This
    normalizes those observed confusions so a screen link can still be recovered.

    It is intentionally conservative: the dot-reinsertion only runs behind an
    explicit ``scheme://`` or ``www`` anchor (or a bare ``host/path`` shape) and
    only accepts a host whose final label is a whitelisted TLD — so ordinary
    prose ("example com") and code identifiers are never turned into links.
    """
    # OCR often inserts spaces around punctuation, especially dots and slashes
    # in the address bar (e.g. "https:// secure-login . xyz / verify").
    text = re.sub(r"(?<=\w)\s*\.\s*(?=\w)", ".", text)
    text = re.sub(r"(?<=\w)\s*/\s*(?=\w)", "/", text)

    # 1) Fix a mangled scheme prefix (hltps:/https:/http: followed by I/l/1///…).
    text = re.sub(r"\b[hf]lt?t?ps?\s*[:;]?\s*[Il1/\\|]{1,}", "https://", text, flags=re.I)
    text = re.sub(r"\bhttps?\s*[:;]?\s*[Il1/\\|]{1,}", "https://", text, flags=re.I)
    text = re.sub(r"\bwww\.\s*[Il1/\\|]{1,}", "www.", text, flags=re.I)

    # 2) Rebuild a host whose dots OCR turned into spaces, anchored on scheme://
    #    or www. Walk tokens until the host is complete (its last label is a
    #    known TLD) or a path delimiter is hit; rejoin labels with '.' and keep
    #    any path/remainder intact.
    def _rebuild(prefix: str, rest: str) -> str:
        tokens = rest.split()
        if not tokens:
            return prefix + rest
        host_labels = []
        path = ""
        remainder_start = len(tokens)
        for i, tok in enumerate(tokens):
            if any(c in tok for c in "/?#"):
                head = re.split(r"[/?#]", tok, 1)[0]
                if head:
                    host_labels.append(head)
                    path = tok[len(head):]
                remainder_start = i + 1
                break
            host_labels.append(tok)
            # Stop once the accumulated host already ends in a known TLD
            # (so trailing prose words aren't swallowed into the host).
            if _is_plausible_tld(host_labels[-1].lower().split(".")[-1]):
                remainder_start = i + 1
                break
        if len(host_labels) < 2:
            return prefix + rest
        host = ".".join(host_labels).lower().strip(".,;:!?")
        tld = host.rsplit(".", 1)[-1]
        if "." not in host or not _is_plausible_tld(tld):
            return prefix + rest  # not a plausible host — leave prose alone
        out = prefix + host + path
        remainder = " ".join(tokens[remainder_start:])
        if remainder:
            out += " " + remainder
        return out

    # Repair only the scheme-plus-host prefix. Do not allow the match to
    # consume following prose or a second URL, which previously merged two
    # visible URLs into one fabricated host/path.
    text = re.sub(
        r"(https?://)([^\s/?#]+(?:\s+[^\s/?#]+){0,3})",
        lambda m: _rebuild(m.group(1), m.group(2)),
        text,
    )
    # www anchored (no scheme) → "www paypal com/signin" -> "www.paypal.com/signin"
    text = re.sub(
        r"(?<![a-zA-Z0-9.])(www)(\s+[^\s][a-zA-Z0-9 ./_~?=&%#-]*)",
        lambda m: _rebuild(m.group(1) + ".", m.group(2)),
        text,
    )

    # 3) Bare "host/path" where OCR split the domain dot but kept a path slash:
    #    "bit ly/3xM7" -> "bit.ly/3xM7". Gated on the 2nd label being a TLD AND
    #    being followed by '/', so prose like "example com" stays untouched.
    text = re.sub(
        r"(?<![a-zA-Z0-9.])([a-z0-9][a-z0-9-]*)\s+([a-z]{2,24})(?=/)",
        lambda m: f"{m.group(1)}.{m.group(2)}"
        if m.group(2).lower() in _COMMON_TLDS else m.group(0),
        text,
        flags=re.I,
    )
    return text


# Tolerant host finder for OCR-mangled text: label(.label)*.tld, and only when
# the final label is a plausible TLD (so 'fastapi.testclient' / '19.99' / a
# version '1.2.3' are never treated as links).
_LENIENT_HOST_RE = re.compile(
    r"(?<![a-z0-9.])([a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.([a-z]{2,24}))(?![a-z])",
    re.IGNORECASE,
)


def _lenient_hosts(text: str):
    """Recover plausible hosts from noisy OCR text (may be empty)."""
    text = _repair_ocr_url_noise(text)
    hosts, seen = [], set()

    def _add(host: str, anchored=False):
        host = host.lower().strip(".,;:!?)")
        tld = host.rsplit(".", 1)[-1]
        plausible = _is_plausible_tld(tld) if anchored else tld in _COMMON_TLDS
        if host and plausible and host not in seen:
            seen.add(host)
            hosts.append(host)

    # Scheme/www-anchored spans first (most reliable), then known bare hosts.
    for m in re.finditer(r"(https?://[^\s]+|www\.[^\s]+)", text, re.IGNORECASE):
        span = re.sub(r"^https?://", "", m.group(0), flags=re.IGNORECASE)
        hm = _LENIENT_HOST_RE.search(span)
        if hm:
            _add(hm.group(1), anchored=True)
    for m in _LENIENT_HOST_RE.finditer(text):
        # Skip email local-parts: "user@example.com" is not a link to visit.
        start = m.start(1)
        if start > 0 and text[start - 1] == "@":
            continue
        _add(m.group(1))
    return hosts


def extract_urls_from_text(text):
    """
    Extract valid-looking URLs from a text string, best candidates first.

    Explicit ``http(s)://`` and ``www.`` links are returned before bare
    domains, and a bare domain is only accepted when its final label is a
    plausible TLD — so code identifiers / filenames (e.g. 'fastapi.testclient',
    'torch.dataloader') are not mistaken for links.

    On-screen text comes from OCR, which mangles URL punctuation (``https://``
    becomes ``https:Il`` and a long URL is split across spaces). When the strict
    pattern finds nothing, a tolerant recovery pass rebuilds a plausible host
    from the noisy text so a screen link is still detected.

    Args:
        text: The text to search for URLs.

    Returns:
        list: Normalized URL strings found in the text (best first).
    """
    if not text:
        return []

    # OCR mangles URL punctuation and drops dots between host labels, so repair
    # that noise first — then the strict pattern can match real screen links.
    repaired = _repair_ocr_url_noise(text)
    matches = URL_REGEX.findall(repaired)
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

    results = prioritized + bare
    if results:
        return results

    # Strict pass found nothing — common for OCR text. Recover tolerantly.
    return [f"https://{host}" for host in _lenient_hosts(text)]


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


def _get_active_browser_url():
    """Read the focused browser address bar URL, preserving clipboard contents.

    This is a best-effort Windows fallback for OCR failures. It only reads a
    selected URL from recognized browser windows; it returns None for other apps.
    """
    if sys.platform != "win32":
        return None
    try:
        import pyautogui
        import pyperclip
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        title = (win32gui.GetWindowText(hwnd) or "").lower()
        browser_markers = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")
        if not any(marker in title for marker in browser_markers):
            return None
        previous = pyperclip.paste()
        try:
            pyautogui.hotkey("ctrl", "l")
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.15)
            copied = (pyperclip.paste() or "").strip()
        finally:
            pyperclip.copy(previous or "")
        if not copied or any(ch.isspace() for ch in copied):
            return None
        candidate = copied if re.match(r"^https?://", copied, re.I) else "https://" + copied
        parsed = urlparse(candidate)
        if parsed.hostname and "." in parsed.hostname:
            return candidate
    except Exception as exc:
        print(f"   ℹ️  Active browser URL read unavailable: {type(exc).__name__}")
    return None

def get_active_url():
    """
    Resolve the link the user is looking at.

    Order of resolution:
      1. On-screen URL via OCR
      2. Active browser address bar when OCR could not resolve the page
      3. Clipboard URL only as the final fallback

    This is the main entry point for Zyra's link analysis feature.

    Returns:
        str: The extracted URL string, or None if no URL found.
    """
    print("[ZYRA][ocr] get_active_url START - resolving on-screen/clipboard link")
    try:
        # Prefer the URL visible on screen. A stale copied URL must not override
        # the link the user explicitly asks Zyra to inspect.
        # Capture + OCR runs in an isolated child process so a native
        # EasyOCR/torch/mss crash cannot take down the caller or backend server.
        # The child timeout includes a margin for cold model load + startup.
        print("\n📸 Capturing screen for URL detection...")
        screen_url = _capture_url_isolated(timeout=OCR_TIMEOUT_SECONDS + 60)
        if screen_url:
            print(f"   🔗 URL found on screen: {screen_url}")
            return screen_url
        print("   ℹ️  No on-screen URL (capture produced nothing).")

        # OCR can miss a small or obscured address bar. Before falling back to
        # clipboard (which may be stale), try the active browser's current URL
        # using its address-bar copy shortcut. This does not navigate or modify
        # page state; clipboard is restored immediately after reading.
        url = _get_active_browser_url()
        if url:
            print(f"   🔗 URL read from active browser address bar: {url}")
            return url
        # Fall back to a clipboard URL only after screen/browser capture failed.
        url = _clipboard_exact_url()
        if url:
            print(f"   ✅ URL found in clipboard (fallback): {url}")
            return url
        print("   📋 Checking clipboard for URL...")
        url = get_url_from_clipboard()
        if url:
            print(f"   ✅ URL found in clipboard: {url}")
            return url

        print("   ❌ No URL found on screen or in clipboard.")
        return None
    except BaseException as exc:  # noqa: BLE001 - a capture must never kill the caller
        print(f"[ZYRA][ocr] get_active_url error ({type(exc).__name__}: {exc}) - "
              f"returning no URL. Process stays alive.")
        return None
    finally:
        print("[ZYRA][ocr] get_active_url END - caller continues running")


# ──────────────────────────────────────────────
# 5b. Isolated screen-capture worker (crash containment)
# ──────────────────────────────────────────────
# EasyOCR/torch/mss are native libraries that can SEGFAULT the whole Python
# process — an uncatchable crash that takes the FastAPI server (a daemon thread
# of main.py) down with it, which is exactly the "process exits after a screen
# analysis" bug. Python try/except cannot stop a native crash, so the ONLY
# reliable containment is to run the capture+OCR in a child process: if the
# native stack dies there, only the short-lived child is lost and the server
# keeps running. The child prints the resulting URL (or empty) as its last
# stdout line; a nonzero exit / timeout is treated as "no URL found".

def _ocr_capture_worker() -> int:
    """Child-process entry: capture the screen, OCR it, print the URL.

    Invoked as ``python screen_ocr.py --ocr-capture``. Prints exactly one line
    to stdout: the extracted URL, or an empty line if none was found. All human
    diagnostics go to stderr so stdout stays machine-readable. Exits 0 on a
    normal (even if empty) result; a native crash would abort before the print.
    """
    import json

    def _log(msg: str) -> None:
        try:
            print(msg, file=sys.stderr, flush=True)
        except Exception:
            pass

    try:
        url = None
        images = capture_screens()
        if not images:
            image = capture_screen()
            images = [image] if image is not None else []
        if images:
            _log(f"[ocr-worker] captured {len(images)} physical monitor(s)")
            # Prefer browser chrome/address bars over URLs found in page text.
            for monitor_index, image in enumerate(images, start=1):
                _log(f"[ocr-worker] scanning monitor {monitor_index} "
                     f"({image.size[0]}x{image.size[1]}px)")
                urls = extract_urls_from_image(image)
                if urls:
                    url = urls[0]
                    _log(f"[ocr-worker] URL found on monitor {monitor_index}")
                    break
            if not url:
                _log("[ocr-worker] no URL detected on any monitor")
        else:
            _log("[ocr-worker] screen capture failed")
        # Machine-readable result on stdout (single line).
        sys.stdout.write(json.dumps({"url": url}) + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:  # never let the child traceback confuse the parent
        _log(f"[ocr-worker] error: {type(exc).__name__}: {exc}")
        try:
            sys.stdout.write(json.dumps({"url": None}) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        return 0


def _capture_url_isolated(timeout: float):
    """Capture + OCR the screen in a child process; return a URL or None.

    Contains any native EasyOCR/torch/mss crash to the child so the calling
    (server) process survives. Returns None on no-URL, timeout, or child crash.
    """
    import subprocess

    # In a PyInstaller-frozen build there is no standalone screen_ocr.py to hand
    # to a child interpreter (sys.executable is the app exe, not python). There
    # we can't isolate this way, so run in-process — behaviour matches the
    # pre-isolation code path. Normal dev/venv runs take the isolated branch.
    # The in-process OCR inference is still bounded by _readtext_bounded's
    # timeout + infer lock, and we catch BaseException here so a SystemExit or
    # other escape from the native stack cannot take down the caller.
    if getattr(sys, "frozen", False) or not os.path.isfile(os.path.abspath(__file__)):
        try:
            images = capture_screens()
            if not images:
                image = capture_screen()
                images = [image] if image is not None else []
            for image in images:
                urls = extract_urls_from_image(image)
                if urls:
                    return urls[0]
            return None
        except BaseException as exc:  # noqa: BLE001 - must never kill the caller
            print(f"   ⚠️  Screen OCR failed ({type(exc).__name__}: {exc}); "
                  f"returning no URL. Process stays alive.")
            return None

    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--ocr-capture"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"   ⏱️  Screen OCR subprocess timed out after {timeout:.0f}s.")
        return None
    except Exception as exc:  # spawn failure, etc.
        print(f"   ⚠️  Screen OCR subprocess could not run: {exc}")
        return None

    # Surface the child's diagnostics (stderr) so operators can see what happened.
    for line in (proc.stderr or "").splitlines():
        if line.strip():
            print(f"   {line.strip()}")

    if proc.returncode != 0:
        # A native crash lands here (negative/high exit code) — contained.
        print(f"   ⚠️  Screen OCR subprocess exited abnormally "
              f"(code {proc.returncode}); treating as no URL. Server stays up.")
        return None

    # Last non-empty stdout line is the JSON result.
    url = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            import json
            url = (json.loads(line) or {}).get("url")
        except Exception:
            url = line or None
        break
    return url or None


# Alias for backward compatibility
get_url_smart = get_active_url


# ──────────────────────────────────────────────
# 6. Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Child-process mode: run one isolated screen capture + OCR and exit.
    # Launched by _capture_url_isolated() so a native crash stays contained.
    if "--ocr-capture" in sys.argv:
        raise SystemExit(_ocr_capture_worker())

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
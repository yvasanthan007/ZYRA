"""
speak.py — ZYRA voice output (queued, streaming, interruptible TTS)

What this module guarantees
  • ONE speaker: a single render thread + a single playback thread. Text is
    never synthesized or played twice, and two sentences can never overlap.
  • Sentence-level streaming: ``speak_async()`` returns immediately so the AI
    stream keeps generating while the previous sentence is being spoken.
    Rendered audio is prefetched so sentences chain together naturally.
  • Barge-in: ``stop_speaking()`` instantly stops playback, drops everything
    queued and invalidates in-flight synthesis, so an interrupted answer can
    never "come back" after the user starts a new request.
  • Natural voice: Microsoft Edge neural voices, calm male voice by default,
    moderate rate and slight depth.
  • Only clean, speakable text is ever voiced — markdown, emoji, ANSI codes,
    log prefixes ("brain:", "AI error …") and debug output are stripped.

Environment configuration
  ZYRA_TTS_VOICE=en-US-AndrewNeural     (calm, natural, slightly deep)
  ZYRA_TTS_RATE=+4%                     (moderate conversational pace)
  ZYRA_TTS_PITCH=-2Hz                   ("" disables the pitch tweak)
  ZYRA_TTS_VOLUME=+0%
  ZYRA_TTS_MAX_RETRIES=3
"""

import asyncio
import os
import queue
import re
import tempfile
import threading
import time
from typing import Iterable, List, Optional

# ── Windows console safety ──────────────────────────────────────────────
# Force UTF-8 output so status prints never crash with UnicodeEncodeError on a
# cp1252 console (same guard used by main.py / start_zyra.py).
import sys as _sys

for _stream in (_sys.stdout, _sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

import edge_tts

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

DEFAULT_VOICE = "en-US-AndrewNeural"          # calm, composed, slightly deep
FALLBACK_VOICES = ("en-US-GuyNeural", "en-US-AriaNeural")

VOICE = os.environ.get("ZYRA_TTS_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE
RATE = os.environ.get("ZYRA_TTS_RATE", "+4%").strip()
PITCH = os.environ.get("ZYRA_TTS_PITCH", "-2Hz").strip()
VOLUME = os.environ.get("ZYRA_TTS_VOLUME", "+0%").strip()

MAX_RETRIES = max(1, int(os.environ.get("ZYRA_TTS_MAX_RETRIES", "3")))
RETRY_DELAY = 0.6              # seconds, multiplied by the attempt number
MAX_TEXT_LEN = 2000

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_WS_RE = re.compile(r"\s+")
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKS_RE = re.compile(r"[*_#>|~]+")
_LIST_PREFIX_RE = re.compile(r"(?m)^\s*(?:[-•*\u2022]|\d+[.)])\s+")
# Bare code lines / function calls must never be read aloud.
_CODE_LINE_RE = re.compile(
    r"^\s*(?:print|console\.log|echo|def\s+\w+|class\s+\w+|import\s+\w+"
    r"|from\s+\w+\s+import|#include|public\s+\w+|[{}<>/]"
    r"|[a-zA-Z_][\w.]*\s*\([^()]*\)\s*;?\s*$)"
)

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\uFE0F\u200d]"
)
_LOG_PREFIX_RE = re.compile(r"^\s*(?:brain|zyra|tts|stt|debug|info|warning|error)\s*:", re.I)
_INTERNAL_KEYWORDS = (
    "brain", "zyra", "tts", "stt", "ollama", "debug", "traceback",
    "exception", "warning", "warn", "error", "failed", "microphone",
)


def _looks_like_internal_log(line: str) -> bool:
    """True for status/error/log lines that must never be spoken.

    Catches anchored log prefixes ("brain: ...") and decorated log records such
    as "⚠️  TTS render error: boom". A colon is required for the keyword check,
    so a normal answer that merely mentions a word (e.g. "TTS stands for text
    to speech.") is still spoken.
    """
    if _LOG_PREFIX_RE.match(line):
        return True
    if ":" not in line and "：" not in line:
        return False
    head = re.split(r"[:：]", line, 1)[0].lower()
    words = re.findall(r"[a-z_]+", head)
    return any(word in _INTERNAL_KEYWORDS for word in words)



# ──────────────────────────────────────────────
# Text sanitising
# ──────────────────────────────────────────────

def sanitize_tts_text(text) -> str:
    """Turn arbitrary model output into clean, natural speech text.

    Removes markdown/code, emoji, ANSI codes and log prefixes, collapses
    whitespace and caps the length. Returns "" when there is nothing
    speakable — internal logs are never voiced.
    """
    if not text:
        return ""
    t = str(text)
    t = _ANSI_RE.sub("", t)
    t = _CODE_BLOCK_RE.sub(" ", t)
    t = _MD_LINK_RE.sub(r"\1", t)
    t = _INLINE_CODE_RE.sub(r"\1", t)
    t = _CONTROL_CHAR_RE.sub(" ", t)
    t = _EMOJI_RE.sub("", t)

    lines = []
    for line in t.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _looks_like_internal_log(stripped):   # never voice internal logs
            continue
        if _CODE_LINE_RE.match(stripped):        # never voice code
            continue
        lines.append(stripped)
    t = " ".join(lines)

    t = _LIST_PREFIX_RE.sub("", t)
    t = _MD_MARKS_RE.sub("", t)
    t = _WS_RE.sub(" ", t).strip()
    if not re.search(r"\w", t, flags=re.UNICODE):    # punctuation only
        return ""
    if len(t) > MAX_TEXT_LEN:
        t = t[:MAX_TEXT_LEN].rstrip()
    return t


# ──────────────────────────────────────────────
# Internal state (single speaker)
# ──────────────────────────────────────────────

_lock = threading.Lock()
_cond = threading.Condition(_lock)
_queue: "queue.Queue" = queue.Queue()                   # text waiting to synthesize
_render_queue: "queue.Queue" = queue.Queue(maxsize=2)   # rendered, awaiting play
_generation = 0                # bumped on every interrupt: stale work is dropped
_outstanding = 0               # enqueued-but-not-yet-spoken utterances
_playing = False
_current_text: Optional[str] = None
_recent_spoken: List[str] = []  # newest last (echo detection for barge-in)
_RECENT_MAX = 6

_render_thread: Optional[threading.Thread] = None
_player_thread: Optional[threading.Thread] = None
_threads_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None

_STOP = object()               # queue sentinel


# ──────────────────────────────────────────────
# Synthesis (Edge neural voices, with retry)
# ──────────────────────────────────────────────

def _render_sync(text: str, output_file: str, voice: str,
                 rate: str, pitch: str, volume: str) -> bool:
    """Render ``text`` to ``output_file`` using the shared event loop."""
    async def _run() -> bool:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                kwargs = {}
                if rate:
                    kwargs["rate"] = rate
                if volume:
                    kwargs["volume"] = volume
                if pitch:
                    kwargs["pitch"] = pitch
                try:
                    communicate = edge_tts.Communicate(text, voice, **kwargs)
                except TypeError:            # older edge-tts without pitch
                    communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_file)
                if os.path.getsize(output_file) > 0:
                    return True
            except Exception:
                pass
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)
        return False

    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(_run())


def _render_with_voice_fallback(text: str, output_file: str) -> bool:
    """Try the configured voice, then the fallback voices (single voice source)."""
    voices = [VOICE] + [v for v in FALLBACK_VOICES if v != VOICE]
    for voice in voices:
        if _render_sync(text, output_file, voice, RATE, PITCH, VOLUME):
            return True
        # Retry that voice without the rate/pitch tweaks (some voices reject
        # pitch) before falling through to the next voice.
        if _render_sync(text, output_file, voice, "", "", ""):
            return True
    return False


def _safe_remove(path: Optional[str]) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _finish_item(done) -> None:
    """Mark one utterance consumed and wake any waiters."""
    global _outstanding
    with _cond:
        if _outstanding > 0:
            _outstanding -= 1
        if done is not None:
            done.set()
        _cond.notify_all()


def _ensure_mixer() -> bool:
    """Initialise pygame's mixer once (lazy: importing speak is always safe)."""
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Audio output unavailable: {exc}")
        return False


# ──────────────────────────────────────────────
# Workers (render ahead, play strictly in order)
# ──────────────────────────────────────────────

def _render_worker() -> None:
    """Synthesize queued text one sentence ahead of playback."""
    while True:
        item = _queue.get()
        if item is _STOP:
            try:
                _render_queue.put((_STOP, None, None), timeout=1.0)
            except Exception:
                pass
            return

        gen, text, done = item
        with _cond:
            stale = gen != _generation
        if stale:
            _finish_item(done)
            continue

        tmp = None
        ok = False
        try:
            fd, tmp = tempfile.mkstemp(prefix="zyra_tts_", suffix=".mp3")
            os.close(fd)
            ok = _render_with_voice_fallback(text, tmp)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  TTS render error: {exc}")

        if not ok:
            _safe_remove(tmp)
            _finish_item(done)
            continue
        try:
            _render_queue.put((gen, (tmp, text), done), timeout=30.0)
        except Exception:
            _safe_remove(tmp)
            _finish_item(done)


def _player_worker() -> None:
    """Play rendered sentences strictly one after another."""
    global _playing, _current_text
    try:
        import pygame
    except Exception as exc:  # pragma: no cover
        print(f"⚠️  pygame missing — voice output disabled ({exc})")
        return

    while True:
        item = _render_queue.get()
        if item[0] is _STOP:
            return
        try:
            gen, payload, done = item
            tmp, text = payload
        except Exception:  # pragma: no cover - defensive unpack guard
            continue

        with _cond:
            stale = gen != _generation
        if stale:
            _safe_remove(tmp)
            _finish_item(done)
            continue
        if not _ensure_mixer():
            _safe_remove(tmp)
            _finish_item(done)
            continue

        try:
            with _cond:
                _playing = True
                _current_text = text
                _recent_spoken.append(text)
                del _recent_spoken[:-_RECENT_MAX]
            print(f"🔊 ZYRA: {text}")
            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                with _cond:
                    if _generation != gen:      # interrupted → stop now
                        break
                time.sleep(0.05)
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  TTS playback error: {exc}")
        finally:
            with _cond:
                _playing = False
                _current_text = None
            _safe_remove(tmp)
            _finish_item(done)


def _ensure_threads() -> None:
    global _render_thread, _player_thread
    with _threads_lock:
        if _render_thread is None or not _render_thread.is_alive():
            _render_thread = threading.Thread(
                target=_render_worker, name="zyra-tts-render", daemon=True
            )
            _render_thread.start()
        if _player_thread is None or not _player_thread.is_alive():
            _player_thread = threading.Thread(
                target=_player_worker, name="zyra-tts-play", daemon=True
            )
            _player_thread.start()


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def speak_async(text) -> bool:
    """Queue ``text`` for speech and return immediately (streaming-friendly).

    Returns True when something speakable was queued, False when the text was
    empty/unspeakable (nothing is ever synthesized twice).
    """
    global _outstanding
    clean = sanitize_tts_text(text)
    if not clean:
        return False
    _ensure_threads()
    with _cond:
        _outstanding += 1
        gen = _generation
    _queue.put((gen, clean, None))
    return True


def speak(text, wait: bool = True, timeout: Optional[float] = None) -> bool:
    """Speak ``text`` (backwards compatible with the original blocking API).

    ``wait=True`` (default) blocks until this text has finished playing, which
    keeps command responses and the DNS/URL voice watchers behaving exactly as
    before. ``wait=False`` is the non-blocking streaming form.
    """
    global _outstanding
    clean = sanitize_tts_text(text)
    if not clean:
        return False

    if not wait:
        return speak_async(clean)

    _ensure_threads()
    done = threading.Event()
    with _cond:
        _outstanding += 1
        gen = _generation
    _queue.put((gen, clean, done))

    # Wait for this utterance. The cap only exists so a wedged audio device can
    # never freeze the caller forever — a single sentence never takes 60s.
    if not done.wait(timeout if timeout is not None else 60.0):
        print("⚠️  TTS wait timed out — continuing without blocking the assistant")
    return True


def wait_until_done(timeout: Optional[float] = None) -> bool:
    """Block until every queued sentence has finished playing.

    Returns True when the queue drained (or was interrupted — an interrupt is
    itself "done"), False when the timeout expired.
    """
    deadline = None if timeout is None else (time.monotonic() + timeout)
    with _cond:
        while _outstanding > 0:
            remaining = None if deadline is None else (deadline - time.monotonic())
            if remaining is not None and remaining <= 0:
                return False
            _cond.wait(timeout=0.25 if remaining is None else min(0.25, remaining))
        return True


def stop_speaking(clear_queue: bool = True) -> None:
    """Interrupt ZYRA immediately (barge-in).

    Stops playback, invalidates in-flight synthesis so it can never be spoken
    afterwards, and optionally drops every queued sentence.
    """
    global _generation, _outstanding
    if clear_queue:
        _drain(_queue)
        _drain(_render_queue)
    with _cond:
        _generation += 1              # stale work is dropped by both workers
    # Stop the current audio outside the lock (pygame call).
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass
    if clear_queue:
        with _cond:
            _outstanding = 0
            _cond.notify_all()


def _drain(q: "queue.Queue") -> None:
    """Empty a queue, waking the workers that may be blocked putting into it."""
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def is_speaking() -> bool:
    """True while audio is playing or sentences are still queued."""
    with _cond:
        return _playing or _outstanding > 0


def recent_spoken() -> List[str]:
    """Recently spoken sentences (newest last) — used for echo rejection."""
    with _cond:
        return list(_recent_spoken)


def get_voice() -> str:
    return VOICE


def set_voice(voice: str) -> None:
    global VOICE
    if voice and voice.strip():
        VOICE = voice.strip()


def warm_up() -> bool:
    """Pre-warm the TTS path so the first sentence is not slowed by a cold
    network/TLS handshake to the voice service. Safe to call at startup."""
    try:
        fd, tmp = tempfile.mkstemp(prefix="zyra_tts_warm_", suffix=".mp3")
        os.close(fd)
        ok = _render_sync("Ready.", tmp, VOICE, RATE, PITCH, VOLUME)
        _safe_remove(tmp)
        return ok
    except Exception:
        return False


def warm_up_async() -> None:
    threading.Thread(target=warm_up, name="zyra-tts-warmup", daemon=True).start()


__all__ = [
    "speak",
    "speak_async",
    "stop_speaking",
    "wait_until_done",
    "is_speaking",
    "recent_spoken",
    "sanitize_tts_text",
    "get_voice",
    "set_voice",
    "warm_up",
    "warm_up_async",
    "VOICE",
]

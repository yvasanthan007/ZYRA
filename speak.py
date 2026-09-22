import asyncio
import os
import re
import tempfile
import threading

import edge_tts
import pygame

VOICE = "en-US-AriaNeural"   # Natural Female Voice

# Edge TTS retry settings. Microsoft's free Edge TTS endpoint intermittently
# returns no audio (NoAudioReceived) under load/throttling, so we retry with
# backoff and fall back to an offline Windows TTS voice if it keeps failing.
MAX_RETRIES = 3
RETRY_DELAY = 1.2          # seconds, multiplied by attempt number
MAX_TEXT_LEN = 2000

# Latency tuning: first TTS attempt gets one fast retry instead of three slow
# ones so a transient endpoint hiccup doesn't stall the voice reply for
# multiple seconds. (Reliability is preserved by the caller's error handling.)
MAX_RETRIES_FIRST_CHUNK = 2

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")

pygame.mixer.init()

# One persistent event loop is created once at import time and reused for
# every TTS call — `asyncio.run()` in the old code built and tore down a full
# event loop (plus a fresh HTTPS connection pool) on every single reply.
_tts_loop = asyncio.new_event_loop()
threading.Thread(target=_tts_loop.run_forever, name="zyra-tts-loop", daemon=True).start()

# Tracks the currently-playing audio so a new interaction can cleanly
# interrupt the previous utterance instead of speaking over it.
_speak_lock = threading.Lock()


def sanitize_tts_text(text):
    """Clean text before sending it to the TTS service.

    Strips control characters, collapses whitespace and trims the input.
    Returns an empty string when there is nothing meaningful to speak.
    """
    if not text:
        return ""
    t = _CONTROL_CHAR_RE.sub(" ", text)
    t = _WS_RE.sub(" ", t).strip()
    if len(t) > MAX_TEXT_LEN:
        t = t[:MAX_TEXT_LEN].rstrip()
    return t


def _sapi_fallback(text):
    """Offline Windows SAPI voice, used only when Edge TTS keeps failing.

    Uses the built-in System.Speech on Windows so ZYRA can still speak without
    depending on Microsoft's online endpoint. Returns True on success.
    """
    # Disabled: the system SAPI fallback can introduce a second voice.
    return False
    try:
        safe = text.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Speak('{0}')".format(safe)
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=180,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _speak_text_now(text):
    """Blocking convenience used by the async helpers below.

    Runs `wait_for_speech` on the persistent loop and returns its result.
    """
    future = asyncio.run_coroutine_threadsafe(
        _render_audio(text, _get_output_file()), _tts_loop
    )
    return future.result()


async def _render_audio(text, output_file):
    """Synthesize text to the output mp3 file with retry + non-empty check.

    Returns True if a non-empty audio file was produced.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(text, VOICE)
            await communicate.save(output_file)
            if os.path.getsize(output_file) > 0:
                return True
        except Exception:
            pass
        # Small backoff before retrying; also allows a cold re-connect.
        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY * attempt)
    return False


def _get_output_file():
    """Stable temp path reused between calls (no churn of temp files)."""
    temp_dir = tempfile.gettempdir()
    return os.path.join(temp_dir, "zyra_voice.mp3")


def stop_speaking():
    """Immediately stop any currently-playing TTS audio.

    Used when the user starts a new interaction while ZYRA is still talking,
    so the old response never speaks over the new one.
    """
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
    except Exception:
        pass


async def _speak_async(text):
    # Reuse a stable temp file path instead of creating/deleting a new one
    # for every utterance.
    output_file = _get_output_file()

    success = await _render_audio(text, output_file)
    if not success:
        return False

    pygame.mixer.music.load(output_file)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        await asyncio.sleep(0.1)

    pygame.mixer.music.unload()

    # Clean up temp file
    try:
        if os.path.exists(output_file):
            os.remove(output_file)
    except Exception:
        pass

    return True


def speak(text):
    text = sanitize_tts_text(text)
    if not text:
        print("Zyra: (nothing to say)")
        return

    print(f"Zyra: {text}")

    spoke = False
    try:
        # Check if mixer is initialized
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        with _speak_lock:
            # A fresh interaction interrupts whatever was still playing.
            stop_speaking()
            future = asyncio.run_coroutine_threadsafe(_speak_async(text), _tts_loop)
            spoke = future.result()
    except Exception as e:
        print(f"TTS Error: {e}")

    # Keep one voice source: never fall back to the system SAPI voice.
    if not spoke:
        print("TTS unavailable: configured Edge voice could not speak aloud.")

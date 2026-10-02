import asyncio
import os
import re
import sys
import tempfile
import subprocess

import edge_tts
import pygame

# Windows console encoding safety for non-ASCII text output
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

VOICE = "en-US-AriaNeural"   # Natural Female Voice

# Edge TTS retry settings. Microsoft's free Edge TTS endpoint intermittently
# returns no audio (NoAudioReceived) under load/throttling, so we retry with
# backoff and fall back to an offline Windows TTS voice if it keeps failing.
MAX_RETRIES = 3
RETRY_DELAY = 1.2          # seconds, multiplied by attempt number
MAX_TEXT_LEN = 2000

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")

pygame.mixer.init()


def _get_voice_for_text(text: str) -> str:
    """Select the best Edge TTS voice based on script detection in text."""
    if re.search(r"[\u0900-\u097F]", text):  # Devanagari / Hindi script
        return "hi-IN-SwaraNeural"
    if re.search(r"[\u0B80-\u0BFF]", text):  # Tamil script
        return "ta-IN-PallaviNeural"
    return VOICE


# Long URLs make TTS spell every character out loud ("B08N5WRWNW" becomes
# "bee oh eight en five double you..."), which turns a short verdict into a
# 15-25 second monologue. Speak just the host so the warning stays snappy.
_URL_SPOKEN_RE = re.compile(
    r"(?:https?://|www\.)([^/\s?#]+)(?:[/?#]\S*)?", re.IGNORECASE
)


def shorten_url_for_speech(url: str) -> str:
    """Reduce a URL to its host so speech engines pronounce it quickly."""
    if not url:
        return "this link"
    match = _URL_SPOKEN_RE.search(str(url).strip())
    host = (match.group(1) if match else str(url).strip()).rstrip("/")
    # Drop a leading "www." and any credentials/port noise.
    host = re.sub(r"^www\.", "", host, flags=re.IGNORECASE).split("@")[-1]
    host = host.split(":")[0]
    if not host or "." not in host:
        return "this link"
    return host


def sanitize_tts_text(text):
    """Clean text before sending it to the TTS service.

    Strips control characters, collapses whitespace, trims the input and
    shortens embedded URLs so they are not spelled out character by character.
    Returns an empty string when there is nothing meaningful to speak.
    """
    if not text:
        return ""
    t = _CONTROL_CHAR_RE.sub(" ", text)
    if _URL_SPOKEN_RE.search(t):
        t = _URL_SPOKEN_RE.sub(lambda m: shorten_url_for_speech(m.group(0)), t)
    t = _WS_RE.sub(" ", t).strip()
    if len(t) > MAX_TEXT_LEN:
        t = t[:MAX_TEXT_LEN].rstrip()
    return t


def _sapi_fallback(text):
    """Offline Windows SAPI voice, used when Edge TTS is unavailable or fails."""
    try:
        safe = text.replace("'", "''").replace('"', '""')
        ps = f"(New-Object -ComObject SAPI.SpVoice).Speak('{safe}')"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


async def _render_audio(text, output_file):
    """Synthesize text to the output mp3 file with retry + non-empty check.

    Returns True if a non-empty audio file was produced.
    """
    voice = _get_voice_for_text(text)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_file)
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return True
        except Exception:
            pass
        # Small backoff before retrying; also allows a cold re-connect.
        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY * attempt)
    return False


async def _speak_async(text):
    # Use a temporary file to avoid conflicts
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, "zyra_voice.mp3")

    success = await _render_audio(text, output_file)
    if not success:
        return False

    try:
        pygame.mixer.music.load(output_file)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)

        pygame.mixer.music.unload()
    except Exception:
        return False

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
        try:
            print("Zyra: (nothing to say)")
        except Exception:
            pass
        return

    try:
        print(f"Zyra: {text}")
    except Exception:
        print(f"Zyra: {text.encode('ascii', errors='replace').decode('ascii')}")

    spoke = False
    try:
        # Check if mixer is initialized
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        spoke = asyncio.run(_speak_async(text))
    except RuntimeError:
        # If event loop is already running, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            spoke = loop.run_until_complete(_speak_async(text))
        finally:
            loop.close()
    except Exception as e:
        print(f"TTS Error: {e}")

    # If Edge TTS fails (e.g. offline/network failure), use SAPI fallback
    if not spoke:
        if not _sapi_fallback(text):
            print("TTS unavailable: configured voice could not speak aloud.")


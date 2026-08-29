import asyncio
import os
import re
import subprocess
import sys
import tempfile

import edge_tts
import pygame

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
    if sys.platform != "win32":
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


async def _speak_async(text):
    # Use a temporary file to avoid conflicts
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, "zyra_voice.mp3")

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

    # Online Edge TTS failed after retries - fall back to offline SAPI voice.
    if not spoke:
        if not _sapi_fallback(text):
            print("TTS unavailable: could not speak aloud.")
        else:
            print("TTS: used offline voice (Edge TTS unavailable).")

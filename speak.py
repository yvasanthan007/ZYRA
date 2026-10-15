import asyncio
import os
import re
import sys
import tempfile
import subprocess
import threading
import edge_tts
import pygame

# Windows console encoding safety for non-ASCII text output
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# Centralized female voice configuration, used by every spoken response.
# JennyNeural is primary; these English (United States) female Edge voices are
# tried in order as fallbacks before resorting to offline Windows SAPI speech.
DEFAULT_VOICE = "en-US-JennyNeural"
FALLBACK_VOICES = ("en-US-AriaNeural", "en-US-AvaNeural", "en-US-EmmaNeural")
VOICE = DEFAULT_VOICE
# Edge TTS retry settings. Microsoft's free Edge TTS endpoint intermittently
# returns no audio (NoAudioReceived) under load/throttling, so we retry with
# backoff and fall back to an offline Windows TTS voice if it keeps failing.
MAX_RETRIES = 3
RETRY_DELAY = 1.2          # seconds, multiplied by attempt number
MAX_TEXT_LEN = 2000

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")

pygame.mixer.init()

# ── Single-in-flight speech policy ──────────────────────────────────────────
# Only one utterance may synthesize and play at a time. Every speak() call
# takes this lock before touching the TTS pipeline or the shared pygame
# mixer, so concurrent requests (e.g. several POST /api/speak calls) queue
# up instead of playing over each other. threading.Lock is used because
# speak() may run on worker threads (FastAPI, the voice loop) — an asyncio
# Lock would not protect cross-thread callers.
_speak_lock = threading.Lock()

# Hook-driven interruption. When stop_speaking() is called, the flag below is
# raised and the active pygame playback is halted; the running synthesis /
# playback loop checks the flag and releases the lock promptly, so a stop
# reaches the backend audio itself and never leaves the pipeline wedged.
_stop_requested = threading.Event()


def stop_speaking() -> bool:
    """Interrupt any in-flight synthesis or playback.

    Stops real backend audio (pygame mixer) immediately and flags the
    pipeline to abort, so the single-in-flight lock is released as soon as
    the current step notices the stop. Returns True when playback was
    actually halted; the flag is always raised so a synthesis still in
    progress aborts before it ever starts playing.
    """
    _stop_requested.set()
    halted = False
    try:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            halted = True
    except Exception:
        pass
    return halted


def _get_voice_for_text(text: str) -> str:
    # One configured voice is used for every spoken response.
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
    """Offline Windows SAPI voice, used when Edge TTS is unavailable or fails.

    The local fallback cannot match a specific Edge neural identity. Use it
    only when Edge TTS has failed; normal speech always uses the configured
    Edge voice above.
    """
    try:
        safe = text.replace("'", "''").replace('"', '""')
        ps = (
            "$v = New-Object -ComObject SAPI.SpVoice; "
            f"[void]$v.Speak('{safe}')"
        )
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

    JennyNeural is always attempted first. Any fallback to another Edge voice
    is reported to the console so a voice substitution is never silent.
    Returns True if a non-empty audio file was produced.
    """
    voices = (_get_voice_for_text(text), *FALLBACK_VOICES)
    for index, voice in enumerate(voices):
        for attempt in range(1, MAX_RETRIES + 1):
            if _stop_requested.is_set():
                # Interrupted: stop before starting another synthesis attempt.
                return False
            try:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_file)
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    if index > 0:
                        # Never silently substitute: tell the user which
                        # non-primary voice produced this audio.
                        try:
                            print(
                                f"TTS: {voices[0]} unavailable — "
                                f"using fallback voice {voice} instead."
                            )
                        except Exception:
                            pass
                    return True
            except Exception:
                pass
            # Small backoff before retrying; also allows a cold re-connect.
            # The backoff is interruptible so a stop request is honoured even
            # while waiting between retries.
            if attempt < MAX_RETRIES and not _stop_requested.is_set():
                await asyncio.sleep(RETRY_DELAY * attempt)
    return False


async def _speak_async(text):
    # Use a temporary file to avoid conflicts
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, "zyra_voice.mp3")

    try:
        if _stop_requested.is_set():
            return False

        success = await _render_audio(text, output_file)
        if not success or _stop_requested.is_set():
            return False

        try:
            pygame.mixer.music.load(output_file)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if _stop_requested.is_set():
                    # Interruption reaches the actual backend playback here.
                    pygame.mixer.music.stop()
                    break
                await asyncio.sleep(0.1)

            pygame.mixer.music.unload()
        except Exception:
            return False

        return not _stop_requested.is_set()
    finally:
        # Clean up temp file on success, failure and interruption alike so a
        # stopped or failed run never leaks audio files.
        try:
            if os.path.exists(output_file):
                os.remove(output_file)
        except Exception:
            pass


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

    # Single-in-flight: a second caller waits here until the current
    # utterance finishes (or is stopped), so audio never overlaps. The lock
    # is always released — including on failure paths — and a stale stop
    # request from a previous utterance is cleared before this one starts.
    with _speak_lock:
        _stop_requested.clear()
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
            except Exception as e:
                # A failure here must not escape speak() (it would skip the
                # fallback messaging and surface in the worker thread); the
                # `with _speak_lock` above still releases the lock either way.
                print(f"TTS Error: {e}")
            finally:
                loop.close()
        except Exception as e:
            print(f"TTS Error: {e}")

        # Keep the Edge voice as the default, but fall back to the Windows voice
        # when synthesis/playback fails so the user still hears Zyra. Never fall
        # back after an explicit stop: that would start new audio right after
        # the user asked for silence.
        if _stop_requested.is_set():
            return
        if not spoke and _sapi_fallback(text):
            print("TTS: using the Windows voice because Edge TTS was unavailable.")
        elif not spoke:
            print("TTS unavailable: both Edge TTS and Windows speech failed.")


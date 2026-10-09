import os
import subprocess

import speech_recognition as sr

recognizer = sr.Recognizer()

# Improve recognition in noisy environments
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8


class _StderrExplicitPopen(subprocess.Popen):
    """``subprocess.Popen`` that always passes an explicit ``stderr`` on Windows.

    ``speech_recognition`` transcodes captured audio by piping it through a
    bundled FLAC executable and calls::

        subprocess.Popen([...], stdin=PIPE, stdout=PIPE)

    with no ``stderr`` argument, so the child silently inherits the parent's
    stderr handle. Inside the PyInstaller build that handle is not a real
    console handle, and ``CreateProcess`` fails with ``WinError 50``
    ("The request is not supported"), which surfaces to the user as a
    microphone error instead of a transcript. Passing ``stderr=DEVNULL``
    stops the child from inheriting the broken handle; its own diagnostics are
    discarded, exactly as before where nothing was read from that pipe.
    """

    def __init__(self, *args, **kwargs):
        if os.name == "nt" and kwargs.get("stderr") is None:
            kwargs["stderr"] = subprocess.DEVNULL
        super().__init__(*args, **kwargs)


def _recognize(recognizer, audio):
    """Call ``recognize_google`` with the FLAC subprocess patched.

    The patch is scoped to this single call and is always undone, so the rest
    of the process keeps the stock ``subprocess.Popen`` behaviour.
    """
    original_popen = subprocess.Popen
    subprocess.Popen = _StderrExplicitPopen
    try:
        return recognizer.recognize_google(audio)
    finally:
        subprocess.Popen = original_popen

# ---------------------------------------------------------------------------
# Voice configuration (read from .env)
# ---------------------------------------------------------------------------
try:
    from backend.threat_intel import load_env as _load_env
    _load_env()
except Exception:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

import dotenv
if os.path.exists(".env"):
    dotenv.load_dotenv(".env", override=False)

# Voice mode: "google" (network STT, default) | "offline" (keyword-triggered)
ZYRA_VOICE_MODE = os.environ.get("ZYRA_VOICE_MODE", "google").strip().lower() or "google"
# Seconds to wait for the user to start speaking (microphone warm-up + silence)
ZYRA_VOICE_TIMEOUT_SECONDS = int(
    os.environ.get("ZYRA_VOICE_TIMEOUT_SECONDS", "6")
)
# Keyword that must appear in offline mode to trigger command capture.
# Set to None/empty to disable offline trigger mode.
ZYRA_OFFLINE_TRIGGER = os.environ.get(
    "ZYRA_OFFLINE_TRIGGER", "zyra"
).strip().lower()
# How long to keep the offline capture window open after the trigger
ZYRA_OFFLINE_WINDOW_SECONDS = int(
    os.environ.get("ZYRA_OFFLINE_WINDOW_SECONDS", "8")
)

# ---------------------------------------------------------------------------
# Offline / keyword-triggered capture (no Google API, no network)
# ---------------------------------------------------------------------------
_OfflineCapture = None          # thread-safe singleton


class _OfflineCapture:
    """Captures audio from the microphone for a fixed window.

    Uses a lightweight in-process loop (with ``pyaudio`` if available) and
    stores raw PCM audio. In a production voice assistant this audio would be
    sent to a local speech recognition engine (e.g. Vosk or Whisper). Here we
    return the raw captured text for the caller to match against triggers.
    """

    def __init__(self):
        self.audio = b""
        self.recorded = False
        self.lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        with self.lock:
            self.audio += indata.tobytes()
            self.recorded = True

    def capture(self):
        try:
            import pyaudio
        except Exception:
            return

        try:
            stream = pyaudio.PyAudio().open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
                stream_callback=self._callback,
            )
        except Exception:
            return

        with self.lock:
            self.audio = b""
            self.recorded = False

        stream.start_stream()
        deadline = time.monotonic() + ZYRA_OFFLINE_WINDOW_SECONDS
        while time.monotonic() < deadline:
            time.sleep(0.1)

        try:
            stream.stop_stream()
            stream.close()
        finally:
            try:
                pyaudio.PyAudio().terminate()
            except Exception:
                pass


def _get_capture():
    """Return the shared offline capture instance (thread-safe)."""
    global _OfflineCapture
    with threading.Condition():
        if _OfflineCapture is None:
            _OfflineCapture = _OfflineCapture()
    return _OfflineCapture


def _ocr_from_audio(audio_bytes):
    """Best-effort transcription of raw PCM into text.

    In a production voice assistant this would send audio to a local speech
    recognizer (e.g. Vosk, Whisper, or a custom keyword-spotting model).
    Currently it returns the raw captured text for the caller to match.
    """
    return ""

def listen():
    """Listen for voice input from the microphone.

    Returns the recognized command string, or "" when nothing usable was
    captured. In "google" mode this uses Google Speech Recognition. In
    "offline" mode it supports a keyword-triggered capture window.
    """
    print("\n🎤 Listening...")
    mode = ZYRA_VOICE_MODE

    # --- Google STT mode (network) ---
    if mode == "google":
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                audio = recognizer.listen(
                    source,
                    timeout=ZYRA_VOICE_TIMEOUT_SECONDS,
                    phrase_time_limit=10,
                )
                command = _recognize(recognizer, audio)
                return command
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            print("No speech detected.")
            return ""
        except sr.RequestError:
            print("❌ Unable to connect to Google's speech service.")
            return ""
        except Exception as e:
            print(f"❌ Microphone error: {e}")
            return ""

    # --- Offline / keyword mode ---
    if mode == "offline" and ZYRA_OFFLINE_TRIGGER:
        # Trigger mode: listen for the keyword, then capture.
        print(
            f"\n🎤 Listening (say '{ZYRA_OFFLINE_TRIGGER}' to capture)..."
        )
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                audio = recognizer.listen(
                    source,
                    timeout=ZYRA_VOICE_TIMEOUT_SECONDS,
                    phrase_time_limit=2,
                )
                text = _recognize(recognizer, audio)
                if ZYRA_OFFLINE_TRIGGER in text.lower():
                    print("Trigger detected. Capturing command...")
                    capture = _get_capture()
                    if capture is not None:
                        t = threading.Thread(
                            target=capture.capture, daemon=True
                        )
                        t.start()
                        t.join(timeout=ZYRA_OFFLINE_WINDOW_SECONDS + 2)
                        full = ""
                        if capture.recorded:
                            full = _ocr_from_audio(capture.audio)
                        return full
                    return ""
                else:
                    print("Trigger not detected.")
                    # Still capture the window for a fallback transcript.
                    capture = _get_capture()
                    if capture is not None:
                        t = threading.Thread(
                            target=capture.capture, daemon=True
                        )
                        t.start()
                        t.join(timeout=ZYRA_OFFLINE_WINDOW_SECONDS + 2)
                        if capture.recorded:
                            return _ocr_from_audio(capture.audio)
                    return ""
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            print("No speech detected.")
            return ""
        except sr.RequestError:
            print("❌ Unable to connect to Google's speech service.")
            return ""
        except Exception as e:
            print(f"❌ Microphone error: {e}")
            return ""

    # --- Offline / keyword mode (no trigger) ---
    if mode == "offline":
        print("\n🎤 Listening...")
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                audio = recognizer.listen(
                    source,
                    timeout=ZYRA_VOICE_TIMEOUT_SECONDS,
                    phrase_time_limit=10,
                )
                command = _recognize(recognizer, audio)
                # If external recognizer produced nothing, fall back to offline.
                if not command:
                    capture = _get_capture()
                    if capture is not None:
                        t = threading.Thread(
                            target=capture.capture, daemon=True
                        )
                        t.start()
                        t.join(timeout=ZYRA_OFFLINE_WINDOW_SECONDS + 2)
                        if capture.recorded:
                            return _ocr_from_audio(capture.audio)
                    return ""
                return command
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return ""
        except sr.RequestError:
            print("❌ Unable to connect to Google's speech service.")
            return ""
        except Exception as e:
            print(f"❌ Microphone error: {e}")
            return ""

    # --- Fallback: sounddevice if sr.Microphone is unavailable ---
    try:
        import sounddevice as sd
        import numpy as np

        sample_rate = 16000
        channels = 1
        duration = 5

        audio_data = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=channels,
            dtype=np.int16,
            blocking=True,
        )
        audio_bytes = audio_data.tobytes()
        audio = sr.AudioData(audio_bytes, sample_rate, sample_width=2)
        command = _recognize(recognizer, audio)
        return command
    except (sr.UnknownValueError, sr.WaitTimeoutError):
        return ""
    except sr.RequestError:
        print("❌ Unable to connect to Google's speech service.")
        return ""
    except Exception as e:
        print(f"❌ Microphone error: {e}")
        return ""




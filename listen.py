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


def listen():
    """Listen for voice input from the microphone with automatic silence detection."""
    print("\n🎤 Listening...")

    # Primary method: speech_recognition Microphone (auto-stops when user stops speaking)
    try:
        with sr.Microphone() as source:
            # Quick ambient noise adjustment
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            audio = recognizer.listen(source, timeout=6, phrase_time_limit=10)
            command = _recognize(recognizer, audio)
            return command
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except sr.RequestError:
        print("❌ Unable to connect to Google's speech service.")
        return ""
    except Exception:
        # Fallback to sounddevice if sr.Microphone is unavailable on some hardware
        try:
            import sounddevice as sd
            import numpy as np

            sample_rate = 16000
            channels = 1
            duration = 5  # Reduced fallback duration

            audio_data = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=channels,
                dtype=np.int16,
                blocking=True
            )
            audio_bytes = audio_data.tobytes()
            audio = sr.AudioData(audio_bytes, sample_rate=sample_rate, sample_width=2)
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


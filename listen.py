import queue
import time

import numpy as np
import sounddevice as sd
import speech_recognition as sr

# A single recognizer instance is created once at import time and reused for
# every turn — no repeated initialization per request.
recognizer = sr.Recognizer()

# Improve recognition in noisy environments
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
# Silence that ends a phrase. Lower than the 0.8s default so ZYRA reacts
# quickly after the user stops speaking, while still allowing natural pauses.
recognizer.pause_threshold = 0.5
# Ignore very short blips when deciding speech has started/ended.
recognizer.phrase_threshold = 0.2
recognizer.non_speaking_duration = 0.4

# ── Audio / VAD configuration ───────────────────────────────────────────
SAMPLE_RATE = 16000      # matches Google STT's expected rate, no resampling
CHANNELS = 1             # mono
BLOCK_FRAMES = 800       # 50 ms blocks — good latency/accuracy trade-off
MAX_RECORD_SECONDS = 10  # hard cap so a stuck mic can't hang the loop
MIN_SPEECH_MS = 200      # ignore clicks/-breaths shorter than this
# RMS above _noise_floor_mult × measured noise floor counts as speech.
_NOISE_FLOOR_MULT = 2.2
_NOISE_FLOOR_MIN = 120.0

_tts_playing_check = None  # optional callback injected by speak.py


def _rms(block: np.ndarray) -> float:
    """Root-mean-square energy of an int16 block."""
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))


def listen():
    """Stream microphone audio with voice-activity endpointing.

    Recording stops as soon as the user pauses for `pause_threshold`
    seconds after speaking — instead of always waiting out a fixed
    10-second window — so transcription starts almost immediately
    after the user finishes speaking.
    """
    try:
        print("\n🎤 Listening...")

        blocks = queue.Queue()
        audio_frames = []
        speech_started = False
        speech_ms = 0
        silence_ms = 0
        noise_floor = _NOISE_FLOOR_MIN

        def _callback(indata, frames, time_info, status):
            # Cheap copy into the queue; the recording thread only copies,
            # never processes, keeping the stream callback real-time safe.
            blocks.put(indata.copy())

        started = time.monotonic()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=np.int16,
            blocksize=BLOCK_FRAMES,
            callback=_callback,
        ):
            while True:
                try:
                    block = blocks.get(timeout=0.5)
                except Exception:
                    block = None

                if block is not None:
                    level = _rms(block)

                    # Track ambient noise while nobody is speaking so the
                    # VAD adapts to the room (accuracy-safe adaptive gate).
                    if not speech_started:
                        noise_floor = 0.9 * noise_floor + 0.1 * level

                    speech_level = max(
                        _NOISE_FLOOR_MIN, noise_floor * _NOISE_FLOOR_MULT
                    )

                    if level >= speech_level:
                        speech_started = True
                        speech_ms += 50
                        silence_ms = 0
                    elif speech_started:
                        silence_ms += 50

                    if speech_started:
                        audio_frames.append(block)

                elapsed_ms = (time.monotonic() - started) * 1000

                # End of phrase: user spoke (long enough to be real speech)
                # then stayed quiet for pause_threshold. This is what removes
                # the old fixed 10-second wait.
                if (
                    speech_started
                    and speech_ms >= MIN_SPEECH_MS
                    and silence_ms >= recognizer.pause_threshold * 1000
                ):
                    break

                # Nothing said at all within the cap → return empty quickly.
                if elapsed_ms >= MAX_RECORD_SECONDS * 1000:
                    break

        if not audio_frames:
            return ""

        audio_bytes = b"".join(frame.tobytes() for frame in audio_frames)
        audio = sr.AudioData(
            audio_bytes,
            sample_rate=SAMPLE_RATE,
            sample_width=2,  # 16-bit
        )

        try:
            command = recognizer.recognize_google(audio)
            return command

        except sr.UnknownValueError:
            print("❌ I couldn't understand that.")
            return ""

        except sr.RequestError:
            print("❌ Unable to connect to Google's speech service.")
            return ""

        except Exception as e:
            print("Error:", e)
            return ""

    except OSError as e:
        print(f"❌ Microphone error: {e}")
        return ""
    except Exception as e:
        print(f"❌ Listening error: {e}")
        return ""

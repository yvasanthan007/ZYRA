"""
listen.py — ZYRA voice input (streaming VAD capture + local faster-whisper STT)

Pipeline
    microphone (16 kHz, mono, int16)
        → streaming capture + adaptive-energy VAD
        → automatic end-of-speech detection (no manual stop needed)
        → ONE transcription per captured utterance (faster-whisper)

Design rules enforced here
  • Only ONE listening session can be active at a time (module lock +
    session id), so an utterance can never be captured/transcribed twice.
  • The captured audio buffer is transcribed exactly once.
  • Speech is detected automatically: ZYRA never needs to be told when the
    user stopped talking (end-of-speech = sustained silence after speech).
  • Everything is local/offline (faster-whisper). If faster-whisper is not
    installed the module degrades to the previous online recognizer instead
    of crashing, so `python main.py` keeps working.
  • Barge-in support: while listening during ZYRA's own speech, transcripts
    that look like ZYRA's voice (speaker echo) are discarded.

Environment configuration
  ZYRA_STT_MODEL=base.en|small.en|medium.en|distil-small.en|...  (default:
      small.en when CUDA is available, otherwise base.en)
  ZYRA_STT_DEVICE=auto|cpu|cuda            (default auto)
  ZYRA_STT_COMPUTE_TYPE=int8|int8_float16|float16|float32 (default auto)
  ZYRA_STT_LANGUAGE=en|auto                (default en)
  ZYRA_STT_BEAM_SIZE=1                     (greedy = fastest; higher = slower)
  ZYRA_STT_CPU_THREADS=                    (default: cores - 1, max 8)
  ZYRA_MIC_DEVICE=                         (optional sounddevice index/name)
  ZYRA_VAD_SILENCE_MS=700                  (silence that ends an utterance)
  ZYRA_VAD_MIN_SPEECH_MS=300               (shorter = noise, ignored)
  ZYRA_VAD_MAX_UTTERANCE_S=15              (hard cap while someone talks)
  ZYRA_VAD_ENERGY_MULT=3.0                 (speech = mult × noise floor)
  ZYRA_MIC_PREROLL_MS=400                  (audio kept before speech starts)
  ZYRA_BARGE_IN_MIN_MS=900                 (min speech to interrupt normally)
  ZYRA_STT_FALLBACK=1                      (allow online fallback recognizer)
"""

import os
import queue
import threading
import time
from collections import deque
from typing import Callable, List, Optional

import numpy as np
import sounddevice as sd

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

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

SAMPLE_RATE = 16000          # Whisper's native rate — no resampling needed
CHANNELS = 1                 # mono
FRAME_MS = 30                # VAD frame size
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000          # 480 samples
DTYPE = "int16"

SILENCE_MS = int(os.environ.get("ZYRA_VAD_SILENCE_MS", "700"))
MIN_SPEECH_MS = int(os.environ.get("ZYRA_VAD_MIN_SPEECH_MS", "300"))
MAX_UTTERANCE_S = float(os.environ.get("ZYRA_VAD_MAX_UTTERANCE_S", "15"))
ENERGY_MULT = float(os.environ.get("ZYRA_VAD_ENERGY_MULT", "3.0"))
PREROLL_MS = int(os.environ.get("ZYRA_MIC_PREROLL_MS", "400"))
BARGE_IN_MIN_MS = int(os.environ.get("ZYRA_BARGE_IN_MIN_MS", "900"))
# While ZYRA's own voice is in the room, only a clearly louder utterance
# (the user close to the microphone) is treated as an interruption.
BARGE_IN_ENERGY_MULT = float(os.environ.get("ZYRA_BARGE_IN_ENERGY_MULT", "4.5"))
# Absolute floor (int16 RMS) so a very quiet room cannot trigger the VAD on
# numerical noise alone.
MIN_ABS_RMS = float(os.environ.get("ZYRA_VAD_MIN_RMS", "120"))

SILENCE_FRAMES = max(1, SILENCE_MS // FRAME_MS)
MIN_SPEECH_FRAMES = max(1, MIN_SPEECH_MS // FRAME_MS)
PREROLL_FRAMES = max(1, PREROLL_MS // FRAME_MS)
CALIBRATION_FRAMES = max(1, 300 // FRAME_MS)

LANGUAGE = (os.environ.get("ZYRA_STT_LANGUAGE", "en").strip() or "en")
AUTO_LANGUAGE = LANGUAGE.lower() in ("auto", "detect", "multilingual")
BEAM_SIZE = int(os.environ.get("ZYRA_STT_BEAM_SIZE", "1"))
FALLBACK_ENABLED = os.environ.get("ZYRA_STT_FALLBACK", "1").strip() not in ("0", "false", "False")

# Whisper hallucinations on silence/noise — never forwarded to the AI.
_HALLUCINATIONS = {
    "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
    "thank you for watching.", "thanks for watching", "you", "you.", "bye.",
    "bye", "please subscribe", "subscribe", "okay", "okay.", "yeah", "yeah.",
    "hmm", "hm", "uh", "um", ".", "...", "thank you very much.", "♪",
    "please like and subscribe.", "amara.org", "subtitles by",
}

# ──────────────────────────────────────────────
# Global state (one listening session at a time)
# ──────────────────────────────────────────────

_listen_lock = threading.Lock()          # held while capturing audio
_session_lock = threading.Lock()
_session_counter = 0
_listening = False
_stop_requested = threading.Event()


def current_session_id() -> int:
    """Id of the most recently started listening session (0 = none yet)."""
    with _session_lock:
        return _session_counter


def is_listening() -> bool:
    """True while the microphone is actively being captured."""
    return _listening


def stop_listening() -> None:
    """Ask an in-flight listen() call to return immediately (clean shutdown)."""
    _stop_requested.set()


def clear_stop() -> None:
    """Clear a pending stop request (called at the start of a new session)."""
    _stop_requested.clear()


# ──────────────────────────────────────────────
# faster-whisper model (lazy singleton)
# ──────────────────────────────────────────────

_model = None
_model_lock = threading.Lock()
_model_info = {"name": None, "device": None, "compute_type": None, "cuda": False}
_whisper_import_error: Optional[BaseException] = None


def _register_cuda_dll_dirs() -> List[str]:
    """Expose pip-installed CUDA runtime DLLs to ctranslate2 (when present).

    A machine can expose an NVIDIA GPU (device count > 0) while the CUDA runtime
    libraries themselves are not on the DLL search path, which makes inference
    fail with "cublas64_12.dll is not found". If the user has installed the
    `nvidia-*` pip packages (or ctranslate2's CUDA deps that way), this makes
    those DLLs visible so the GPU path can actually be used.
    """
    import importlib.util

    registered: List[str] = []
    candidates = (
        ("nvidia.cublas", "bin"),
        ("nvidia.cudnn", "bin"),
        ("nvidia.cuda_runtime", "bin"),
    )
    for module, sub in candidates:
        try:
            spec = importlib.util.find_spec(module)
        except Exception:
            spec = None
        if spec is None:
            continue
        for location in list(spec.submodule_search_locations or []):
            path = os.path.join(location, sub)
            if os.path.isdir(path):
                try:
                    os.add_dll_directory(path)
                    registered.append(path)
                except Exception:
                    pass
    return registered


def _cuda_available() -> bool:
    """True when ctranslate2 reports a usable NVIDIA GPU."""
    try:
        import ctranslate2  # type: ignore
    except Exception:
        return False
    try:
        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False


def _resolve_device() -> str:
    requested = (os.environ.get("ZYRA_STT_DEVICE", "auto").strip().lower() or "auto")
    if requested == "cpu":
        return "cpu"
    if requested in ("cuda", "gpu"):
        return "cuda" if _cuda_available() else "cpu"
    return "cuda" if _cuda_available() else "cpu"          # auto


def _resolve_compute_type(device: str) -> str:
    requested = (os.environ.get("ZYRA_STT_COMPUTE_TYPE", "").strip() or "")
    if requested:
        return requested
    return "int8_float16" if device == "cuda" else "int8"


def _resolve_model_name(device: str) -> str:
    requested = (os.environ.get("ZYRA_STT_MODEL", "").strip() or "")
    if requested:
        return requested
    # Accuracy first, but never at the cost of unusable latency: a GPU can
    # afford small.en in real time, a CPU-only run stays on base.en.
    return "small.en" if device == "cuda" else "base.en"


def _cpu_threads() -> int:
    requested = os.environ.get("ZYRA_STT_CPU_THREADS", "").strip()
    if requested.isdigit():
        return max(1, int(requested))
    logical = os.cpu_count() or 4
    return max(1, min(8, logical - 1))


def get_model_info() -> dict:
    """Diagnostics about the active STT engine (safe to print at startup)."""
    return dict(_model_info)


def _model_can_run(model) -> bool:
    """Run a tiny real inference — the only reliable compute-backend check.

    A GPU can be visible (device count > 0) while the CUDA runtime DLLs are
    missing, in which case inference raises at decode time. Returning False here
    lets the loader fall back to the CPU instead of silently failing later.
    """
    try:
        probe = np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)
        segments, _info = model.transcribe(
            probe,
            language=None if AUTO_LANGUAGE else LANGUAGE,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        list(segments)          # force the full decode of the probe window
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️  STT backend probe failed: {exc}")
        return False


def _load_model():
    """Load (once) and return a *verified* faster-whisper model.

    Tries GPU then CPU (or just CPU when no GPU is reported) and proves each
    candidate with a real inference before accepting it. Returns None when no
    usable backend exists, so the caller can fall back to the online recognizer.
    """
    global _model, _whisper_import_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on the environment
            _whisper_import_error = exc
            print(f"ℹ️  faster-whisper not available ({exc}); using fallback recognizer")
            return None

        _register_cuda_dll_dirs()
        primary = _resolve_device()
        attempts = [primary] if primary == "cpu" else [primary, "cpu"]
        # Keep the already-chosen model on the CPU fallback (it is normally the
        # one that was just downloaded) unless the user configured a model.
        gpu_model_name = _resolve_model_name(primary)
        configured = os.environ.get("ZYRA_STT_MODEL", "").strip()

        for device in attempts:
            compute_type = _resolve_compute_type(device)
            model_name = configured or (gpu_model_name if device == "cuda"
                                        else _resolve_model_name(device))
            started = time.monotonic()
            try:
                candidate = WhisperModel(
                    model_name,
                    device=device,
                    compute_type=compute_type,
                    cpu_threads=_cpu_threads(),
                    num_workers=1,
                )
                if device != "cpu":
                    ok = _model_can_run(candidate)
                else:
                    ok = True
                if not ok:
                    raise RuntimeError(f"{device} backend not usable")
                _model = candidate
                _model_info.update(
                    {"name": model_name, "device": device,
                     "compute_type": compute_type, "cuda": device == "cuda"}
                )
                print(
                    f"🎙️  STT ready: faster-whisper '{model_name}' on {device} "
                    f"({compute_type}) in {time.monotonic() - started:.1f}s"
                )
                return _model
            except Exception as exc:  # noqa: BLE001 - try the next backend
                _whisper_import_error = exc
                print(f"⚠️  STT init on {device} failed ({type(exc).__name__}: {exc})")
                if device == "cuda":
                    print("   ↪️  Falling back to CPU (install the CUDA runtime — "
                          "cuBLAS 12 + cuDNN 9 — to enable GPU transcription)")

        print("⚠️  STT unavailable — using the online fallback recognizer")
        return None


def warm_up() -> bool:
    """Preload the STT model so the first utterance does not pay the load cost."""
    return _load_model() is not None


def warm_up_async() -> None:
    """Fire-and-forget warm-up in a daemon thread."""
    threading.Thread(target=warm_up, name="zyra-stt-warmup", daemon=True).start()


# ──────────────────────────────────────────────
# Microphone capture with VAD
# ──────────────────────────────────────────────

def _frame_rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    data = frame.astype(np.float32)
    return float(np.sqrt(np.mean(np.square(data))))


def _barge_in_active(barge_in) -> bool:
    """True while ZYRA is speaking.

    ``barge_in`` may be a bool or a callable, so the main loop can hand over
    ``is_speaking`` and have it evaluated per audio frame (a bool sampled once
    would miss the moment playback actually starts).
    """
    try:
        return bool(barge_in() if callable(barge_in) else barge_in)
    except Exception:
        return False


def _capture_utterance(
    timeout: Optional[float],
    should_continue: Optional[Callable[[], bool]],
    barge_in,
):
    """Capture one utterance from the microphone using VAD.

    Returns ``(audio, overlap)`` where ``audio`` is float32 mono speech audio
    and ``overlap`` is True when ZYRA was speaking at some point during the
    capture (i.e. this may be speaker echo rather than the user). Returns
    ``None`` when nothing usable was said / the capture was aborted.
    """
    frames: "queue.Queue" = queue.Queue()

    def _callback(indata, _frames, _time_info, status):  # sounddevice callback
        if status:  # overflow / under-run: VAD tolerates the gap
            pass
        frames.put(indata.copy())

    min_speech_frames = MIN_SPEECH_FRAMES
    barge_frames_needed = max(MIN_SPEECH_FRAMES, BARGE_IN_MIN_MS // FRAME_MS)

    preroll: deque = deque(maxlen=PREROLL_FRAMES)
    captured: List[np.ndarray] = []
    speaking = False
    overlap = False
    speech_frames = 0
    silence_frames = 0
    noise_floor: Optional[float] = None
    calibration_frames = 0
    started_at = time.monotonic()

    device = os.environ.get("ZYRA_MIC_DEVICE", "").strip() or None
    if device is not None and device.isdigit():
        device = int(device)
    max_frames = int(MAX_UTTERANCE_S * 1000 / FRAME_MS)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=FRAME_SAMPLES,
            device=device,
            callback=_callback,
        ):
            while True:
                if _stop_requested.is_set():
                    return None
                if should_continue is not None and not should_continue():
                    return None
                if timeout is not None and (time.monotonic() - started_at) > timeout:
                    return None
                try:
                    frame = frames.get(timeout=0.25)
                except queue.Empty:
                    continue

                playing = _barge_in_active(barge_in)
                if playing:
                    overlap = True

                mono = np.asarray(frame, dtype=np.int16).reshape(-1)
                rms = _frame_rms(mono)

                # Learn the room's noise level during the first ~0.3 s.
                if noise_floor is None and not playing:
                    calibration_frames += 1
                    noise_floor = rms if calibration_frames == 1 else (
                        0.85 * noise_floor + 0.15 * rms
                    )
                    if calibration_frames >= CALIBRATION_FRAMES:
                        noise_floor = max(noise_floor, MIN_ABS_RMS * 0.5)
                    continue
                if noise_floor is None:
                    noise_floor = max(rms, MIN_ABS_RMS * 0.5)

                # While ZYRA talks, the mic also hears the speakers: demand a
                # louder, longer utterance before treating it as the user.
                mult = BARGE_IN_ENERGY_MULT if playing else ENERGY_MULT
                threshold = max(noise_floor * mult, MIN_ABS_RMS)
                is_speech = rms >= threshold

                if not speaking:
                    preroll.append(mono)
                    if is_speech:
                        speaking = True
                        speech_frames = 1
                        silence_frames = 0
                        captured = list(preroll)      # keep the words' onset
                    else:
                        # Slow drift tracking of the background noise level.
                        noise_floor = 0.98 * noise_floor + 0.02 * rms
                    continue

                captured.append(mono)
                if is_speech:
                    speech_frames += 1
                    silence_frames = 0
                    noise_floor = 0.995 * noise_floor + 0.005 * rms
                else:
                    silence_frames += 1
                    if silence_frames >= SILENCE_FRAMES:
                        break                          # automatic end-of-speech
                if len(captured) >= max_frames:
                    break
    except Exception as exc:  # noqa: BLE001 - mic problems must not kill ZYRA
        print(f"⚠️  Microphone error: {exc}")
        return None

    if not captured or speech_frames < min_speech_frames:
        return None
    if overlap and speech_frames < barge_frames_needed:
        return None          # too short to be a deliberate interruption

    audio = np.concatenate(captured).astype(np.float32) / 32768.0
    return audio, overlap


# ──────────────────────────────────────────────
# Transcription
# ──────────────────────────────────────────────

def _looks_like_hallucination(text: str, duration_s: float) -> bool:
    cleaned = text.strip().lower()
    if not cleaned:
        return True
    if cleaned in _HALLUCINATIONS:
        return True
    words = cleaned.replace(".", "").replace(",", "").split()
    if words and len(set(words)) <= 2 and len(words) >= 4:
        return True                       # "you you you you" on noise
    if len(cleaned) <= 2 and duration_s < 1.0:
        return True
    return False


def _transcribe_with_whisper(audio: np.ndarray) -> str:
    """Transcribe the captured buffer ONCE (never re-uses a previous buffer)."""
    model = _load_model()
    if model is None:
        return ""
    try:
        segments, _info = model.transcribe(
            audio,
            language=None if AUTO_LANGUAGE else LANGUAGE,
            beam_size=BEAM_SIZE,
            temperature=0.0,
            vad_filter=True,                     # Silero VAD inside faster-whisper
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,     # never repeat earlier output
            without_timestamps=True,
            word_timestamps=False,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  STT error: {exc}")
        return ""
    return " ".join(parts).strip()


def _transcribe_with_fallback(audio: np.ndarray) -> str:
    """Online recognizer fallback (only when faster-whisper is unavailable)."""
    if not FALLBACK_ENABLED:
        return ""
    try:
        import speech_recognition as sr  # type: ignore
    except Exception:
        return ""
    try:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        pcm = (audio * 32768.0).astype(np.int16).tobytes()
        data = sr.AudioData(pcm, SAMPLE_RATE, 2)
        return recognizer.recognize_google(data) or ""
    except Exception:
        return ""


def _similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_echo(text: str) -> bool:
    """True when the transcript is most likely ZYRA's own voice coming back
    through the speakers while she is still talking."""
    try:
        import speak as _speak  # local import: avoid an import cycle
        spoken = _speak.recent_spoken()
    except Exception:
        spoken = []
    for line in spoken:
        if not line:
            continue
        lowered = text.lower()
        if lowered in line.lower() or line.lower() in lowered:
            return True
        if _similar(text, line) >= 0.55:
            return True
    return False


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def listen(
    timeout: Optional[float] = None,
    should_continue: Optional[Callable[[], bool]] = None,
    barge_in=False,
) -> str:
    """Listen until the user stops speaking and return what they said.

    Args:
        timeout: give up after this many seconds (None = listen until speech
                 arrives; Ctrl+C / stop_listening() always ends the call).
        should_continue: callable checked between frames — return False to end
                 the session (used by the main loop's shutdown flag).
        barge_in: True (or a callable such as ``speak.is_speaking``) while
                 ZYRA is speaking. Enables the echo guard and requires a
                 longer, louder utterance before it interrupts playback.

    Returns:
        The recognized text, or "" when nothing usable was heard.

    Only one listening session may run at a time: a concurrent call returns
    "" immediately instead of opening a second microphone stream.
    """
    global _listening, _session_counter

    if not _listen_lock.acquire(blocking=False):
        print("⚠️  listen() already active — duplicate listening session ignored")
        return ""

    _session_counter += 1
    _listening = True
    clear_stop()
    try:
        print("🎤 Listening...")
        captured = _capture_utterance(timeout, should_continue, barge_in)
        if not captured:
            return ""
        audio, overlap = captured
        if audio is None or audio.size == 0:
            return ""

        duration_s = audio.size / SAMPLE_RATE
        text = _transcribe_with_whisper(audio)
        if not text and _model is None:
            text = _transcribe_with_fallback(audio)

        text = " ".join(text.split()).strip()
        if not text or _looks_like_hallucination(text, duration_s):
            return ""
        if overlap and _is_echo(text):
            print("🔇 (ignored my own voice)")
            return ""

        print(f"📝 You: {text}")
        return text
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - never crash the voice loop
        print(f"⚠️  Listening error: {exc}")
        return ""
    finally:
        _listening = False
        clear_stop()
        _listen_lock.release()


__all__ = [
    "listen",
    "warm_up",
    "warm_up_async",
    "stop_listening",
    "is_listening",
    "current_session_id",
    "get_model_info",
    "SAMPLE_RATE",
]

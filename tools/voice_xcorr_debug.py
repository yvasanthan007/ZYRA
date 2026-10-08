#!/usr/bin/env python3
"""
tools/voice_xcorr_debug.py — Objective answer to "did the mic capture the
playback faithfully?".

Captures mic while playing the known speech WAV, then cross-correlates the
captured signal against the original at several time-scaling factors.
The best-scoring factor tells us whether capture ran at the requested rate
(factor ~1.0 = faithful) or was time-scaled (factor != 1.0 = rate mismatch).
Also runs STT on the best-aligned capture.
"""
import os
import sys
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WAV = os.path.join(ROOT, "tools", "voice_test_speech.wav")

import numpy as np                    # noqa: E402
import sounddevice as sd               # noqa: E402


def load_wav():
    with wave.open(WAV, "rb") as wf:
        rate, ch = wf.getframerate(), wf.getnchannels()
        pcm = wf.readframes(wf.getnframes())
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    return arr, rate


def resample_linear(sig, factor):
    """Time-scale `sig` by `factor` (factor>1 -> played faster)."""
    n = len(sig)
    idx = np.arange(int(n / factor))
    return np.interp(idx, np.arange(n), sig)


def best_xcorr(ref, sig, factors):
    ref_n = ref / (np.abs(ref).max() + 1e-9)
    results = []
    for f in factors:
        s = resample_linear(sig, f)
        n = min(len(ref_n), len(s))
        if n < 1000:
            continue
        a = ref_n[:n] - ref_n[:n].mean()
        b = s[:n] - s[:n].mean()
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
        c = float(np.dot(a, b) / denom)
        results.append((c, f))
    results.sort(reverse=True)
    return results[:5]


def main():
    ref, wrate = load_wav()
    cap_rate = 16000
    seconds = len(ref) / wrate + 3.0

    rec = np.zeros((int(seconds * cap_rate), 1), dtype=np.float64)
    started = threading.Event()

    def cap():
        nonlocal rec
        r = sd.rec(int(seconds * cap_rate), samplerate=cap_rate, channels=1,
                   dtype="int16", blocking=True)
        rec = r.astype(np.float64)
        started.set()

    th = threading.Thread(target=cap, daemon=True)
    th.start()
    started.wait()
    time.sleep(1.0)
    sd.play(ref.astype(np.int16), samplerate=wrate)
    th.join()

    sig = rec[:, 0]
    print(f"captured: peak={int(np.max(np.abs(sig)))} samples={len(sig)}")

    factors = np.arange(0.3, 3.01, 0.05)
    top = best_xcorr(ref, sig, factors)
    print("top cross-correlation (score, time-scale factor):")
    for c, f in top:
        print(f"   corr={c:.3f}  factor={f:.2f}  "
              f"({'captured rate ~ correct' if abs(f - 1.0) < 0.15 else 'RATE SHIFT'})")

    # STT on capture as-is (labelled 16000)
    import speech_recognition as sr
    from listen import _recognize
    audio = sr.AudioData(rec.astype(np.int16).tobytes(),
                         sample_rate=cap_rate, sample_width=2)
    try:
        text = _recognize(sr.Recognizer(), audio)
        print(f"STT as-is: {text!r}")
    except Exception as exc:
        print(f"STT as-is: FAIL {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

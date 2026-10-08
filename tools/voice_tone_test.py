#!/usr/bin/env python3
"""
tools/voice_tone_test.py — Is the capture sample rate what we ask for?

Plays a pure 440 Hz tone from the speakers (generated at 16000 Hz) while the
mic records at a label of 16000 Hz, then FFTs the captured signal:

  peak near 440 Hz   -> device honoured 16000, rates are consistent
  peak near 160 Hz   -> device actually sampled 44100 but data labelled 16000
                        (speech would be slowed ~2.76x -> Google can't decode)

Also saves the mic-during-speech capture to tools/captured_during_playback.wav
for manual listening.
"""
import os
import sys
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np                    # noqa: E402
import sounddevice as sd               # noqa: E402


def fft_peak(sig, rate):
    sig = sig.astype(np.float64)
    sig = sig - sig.mean()
    n = len(sig)
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(sig * win))
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    # ignore DC and very low freq
    lo = freqs > 100
    idx = np.argmax(spec[lo])
    return float(freqs[lo][idx]), float(spec[lo][idx])


def main():
    # CONTROLLED: play at 44100 (device default -> certainly honoured),
    # capture at 44100 and at 16000 labels; FFT both.
    freq = 440.0
    rate_out = 44100
    seconds = 4.0
    t = np.arange(int(seconds * rate_out)) / rate_out
    tone = (np.sin(2 * np.pi * freq * t) * 20000).astype(np.int16)

    for rate_in in (44100, 16000):
        rec = np.zeros((int(seconds * rate_in), 1), dtype=np.int16)
        started = threading.Event()

        def cap():
            nonlocal rec
            rec = sd.rec(int(seconds * rate_in), samplerate=rate_in,
                         channels=1, dtype="int16", blocking=True)
            started.set()

        th = threading.Thread(target=cap, daemon=True)
        th.start()
        started.wait()
        time.sleep(0.8)
        sd.play(tone, samplerate=rate_out)
        th.join()
        sig = rec[:, 0]
        peak_val = int(np.max(np.abs(sig)))
        pk, _ = fft_peak(sig, rate_in)
        ratio = pk / freq
        print(f"capture label={rate_in}: peak={peak_val} dominant={pk:.1f}Hz "
              f"ratio_vs_440={ratio:.3f} -> "
              f"{'HONOURED' if abs(pk - freq) < 30 else 'MISMATCH'}")

    # save a speech capture for manual listening
    with wave.open(os.path.join(ROOT, "tools", "tone_capture.wav"), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate_out)
        wf.writeframes(rec.tobytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

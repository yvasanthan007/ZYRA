#!/usr/bin/env python3
"""
tools/voice_rate_debug.py — Is the 16 kHz capture rate honoured by the device?

Captures the same playback twice (16000 Hz and 44100 Hz labels) and runs STT
on both, then re-labels the 16k capture as 44.1k to detect a rate mismatch.
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
    arr = np.frombuffer(pcm, dtype=np.int16)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1).astype(np.int16)
    return arr, rate


def stt(pcm, rate, label):
    import speech_recognition as sr
    from listen import _recognize
    audio = sr.AudioData(pcm, sample_rate=rate, sample_width=2)
    try:
        text = _recognize(sr.Recognizer(), audio)
        print(f"  STT[{label}] -> {text!r}")
    except Exception as exc:
        print(f"  STT[{label}] -> FAIL {type(exc).__name__}")


def capture_and_play(seconds, rate):
    rec = np.zeros((int(seconds * rate), 1), dtype=np.int16)

    def cap():
        nonlocal rec
        rec = sd.rec(int(seconds * rate), samplerate=rate, channels=1,
                     dtype="int16", blocking=True)

    arr, wrate = load_wav()
    t = threading.Thread(target=cap, daemon=True)
    t.start()
    time.sleep(0.8)
    sd.play(arr, samplerate=wrate)
    t.join()
    return rec


def main():
    info = sd.query_devices(sd.default.device[0])
    print(f"default input: {info['name']}")
    print(f"  default_samplerate={info['default_samplerate']} "
          f"supported_rates... (probing)")

    # What does the device report for 16000?
    for rate in (16000, 44100):
        try:
            s = sd.Stream(device=sd.default.device[0], samplerate=rate,
                          channels=1, dtype="int16")
            s.close()
            print(f"  stream open at {rate}: OK")
        except Exception as exc:
            print(f"  stream open at {rate}: FAIL {exc}")

    arr, wrate = load_wav()
    dur = len(arr) / wrate + 2.5

    print("\n[capture @16000 while playing]")
    rec16 = capture_and_play(dur, 16000)
    pcm16 = rec16.tobytes()
    peak = int(np.max(np.abs(rec16)))
    print(f"  peak={peak} samples={len(rec16)}")

    print("\n[capture @44100 while playing]")
    rec44 = capture_and_play(dur, 44100)
    pcm44 = rec44.tobytes()
    peak44 = int(np.max(np.abs(rec44)))
    print(f"  peak={peak44} samples={len(rec44)}")

    print("\n--- STT matrix ---")
    stt(pcm16, 16000, "as-captured 16k")
    stt(pcm16, 44100, "16k bytes relabeled 44.1k")
    stt(pcm44, 44100, "as-captured 44.1k")
    stt(pcm44, 16000, "44.1k bytes relabeled 16k")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

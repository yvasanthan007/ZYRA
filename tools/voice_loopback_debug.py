#!/usr/bin/env python3
"""
tools/voice_loopback_debug.py — Isolate WHY end-to-end fails.

Plays the known WAV on the default output while recording 16 kHz mono int16
(the exact format listen.py's fallback records), then reports:
  - what output device playback used
  - RMS/peak of what the mic captured during playback
  - STT result of that captured audio
"""
import os
import sys
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WAV = os.path.join(ROOT, "tools", "voice_test_speech.wav")


def main():
    import numpy as np
    import sounddevice as sd

    print("default input :", sd.default.device[0], sd.query_devices(sd.default.device[0])["name"])
    print("default output:", sd.default.device[1], sd.query_devices(sd.default.device[1])["name"])

    with wave.open(WAV, "rb") as wf:
        rate, width, ch = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
        pcm = wf.readframes(wf.getnframes())
    arr = np.frombuffer(pcm, dtype=np.int16)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1).astype(np.int16)
    arr = np.clip(arr.astype(np.int32) * 3, -32768, 32767).astype(np.int16)
    print(f"WAV: rate={rate} ch={ch} samples={len(arr)} dur={len(arr)/rate:.2f}s")

    sr_rec = 16000
    dur = max(6.0, len(arr) / rate + 2)
    rec = np.zeros((int(dur * sr_rec), 1), dtype=np.int16)

    def capture():
        nonlocal rec
        rec = sd.rec(int(dur * sr_rec), samplerate=sr_rec, channels=1,
                     dtype="int16", blocking=True)

    t = threading.Thread(target=capture, daemon=True)
    t.start()
    time.sleep(1.0)
    print("playing...")
    sd.play(arr, samplerate=rate)
    t.join()

    peak = int(np.max(np.abs(rec)))
    rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
    print(f"CAPTURED: peak={peak} rms={rms:.1f} samples={len(rec)}")

    # what did the mic hear? run STT on it
    import speech_recognition as sr_rec_mod
    from listen import _recognize
    audio = sr_rec_mod.AudioData(rec.tobytes(), sample_rate=sr_rec, sample_width=2)
    try:
        text = _recognize(sr_rec_mod.Recognizer(), audio)
        print(f"STT of captured audio: {text!r}")
    except Exception as exc:
        print(f"STT FAIL: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

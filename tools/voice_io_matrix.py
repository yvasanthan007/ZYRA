#!/usr/bin/env python3
"""
tools/voice_io_matrix.py — Cross test mic vs output to find where the
speaker->microphone chain breaks.

  1. ambient capture from the DEFAULT mic (3 s)          -> does mic hear the room?
  2. capture from 'Stereo Mix' while playing the WAV     -> does playback produce sound?
  3. capture from default mic while playing the WAV      -> do speakers reach the mic?
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


def stats(rec, label):
    peak = int(np.max(np.abs(rec)))
    rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
    print(f"  {label:<38} peak={peak:<6} rms={rms:.1f}")
    return peak, rms


def find_device(pred):
    for i, d in enumerate(sd.query_devices()):
        if pred(d):
            return i
    return None


def main():
    print("default device (in,out):", sd.default.device)
    arr, rate = load_wav()

    # 1. ambient from default mic
    print("\n[1] ambient capture from default mic (3s)...")
    rec = sd.rec(3 * 16000, samplerate=16000, channels=1, dtype="int16", blocking=True)
    stats(rec, "ambient default mic")

    # 2. stereo mix while playing (if present)
    stereo = find_device(lambda d: "stereo mix" in d["name"].lower())
    print(f"\n[2] Stereo Mix device index: {stereo}")
    if stereo is not None:
        dur = len(arr) / rate + 1.5
        rec_box = np.zeros((int(dur * 16000), 1), dtype=np.int16)

        def cap():
            nonlocal rec_box
            rec_box = sd.rec(int(dur * 16000), samplerate=16000, channels=1,
                             dtype="int16", device=stereo, blocking=True)

        t = threading.Thread(target=cap, daemon=True)
        t.start()
        time.sleep(0.8)
        sd.play(arr, samplerate=rate)
        t.join()
        stats(rec_box, "stereo mix during playback")

    # 3. default mic while playing
    print("\n[3] default mic during playback (7s)...")
    dur = 7.5
    rec_box = np.zeros((int(dur * 16000), 1), dtype=np.int16)

    def cap2():
        nonlocal rec_box
        rec_box = sd.rec(int(dur * 16000), samplerate=16000, channels=1,
                         dtype="int16", blocking=True)

    t = threading.Thread(target=cap2, daemon=True)
    t.start()
    time.sleep(0.8)
    sd.play(arr, samplerate=rate)
    t.join()
    stats(rec_box, "default mic during playback")

    # 4. STT on whatever the mic heard during playback
    import speech_recognition as sr
    from listen import _recognize
    audio = sr.AudioData(rec_box.tobytes(), sample_rate=16000, sample_width=2)
    try:
        text = _recognize(sr.Recognizer(), audio)
        print(f"\nSTT of mic-during-playback: {text!r}")
    except Exception as exc:
        print(f"\nSTT FAIL: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

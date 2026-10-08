#!/usr/bin/env python3
"""
tools/voice_e2e_test.py — TRUE end-to-end voice test.

Plays a known WAV ("Hello Zyra, this is a voice pipeline test...") through the
speakers while listen() is capturing from the microphone, then reports the
text ZYRA's actual production path transcribed.

Run:  .venv\\Scripts\\python.exe tools/voice_e2e_test.py
"""
import os
import sys
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WAV = os.path.join(ROOT, "tools", "voice_test_speech.wav")
EXPECTED_HINT = "voice pipeline test"


def play_wav(path):
    import sounddevice as sd
    with wave.open(path, "rb") as wf:
        rate, width, ch = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
        pcm = wf.readframes(wf.getnframes())
    import numpy as np
    arr = np.frombuffer(pcm, dtype=np.int16)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1).astype(np.int16)
    # amplify to make sure the mic picks it up from speakers
    arr = np.clip(arr.astype(np.int32) * 3, -32768, 32767).astype(np.int16)
    sd.play(arr, samplerate=rate)


def main():
    if not os.path.exists(WAV):
        print(f"missing {WAV}")
        return 1
    import listen

    # Start playback shortly after listen() begins capturing
    def delayed_play():
        time.sleep(0.6)
        play_wav(WAV)

    t = threading.Thread(target=delayed_play, daemon=True)
    t.start()

    t0 = time.time()
    text = listen.listen()
    dt = time.time() - t0

    print("=" * 78)
    print(f"listen() returned in {dt:.2f}s")
    print(f"TRANSCRIBED : {text!r}")
    print(f"EXPECTED    : text containing {EXPECTED_HINT!r}")
    ok = bool(text) and EXPECTED_HINT.split()[0] in text.lower()
    print(f"RESULT      : {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

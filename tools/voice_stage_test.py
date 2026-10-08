#!/usr/bin/env python3
"""
tools/voice_stage_test.py — Stage-by-stage diagnosis of ZYRA's voice pipeline.

Stages covered (MICROPHONE -> SPEAKER):

  S1  microphone enumeration        (sounddevice)
  S2  speech_recognition Microphone (PyAudio) — listen.py primary path
  S3  audio capture                 (sounddevice fallback used by listen.py)
  S4  captured audio validity       (non-empty, non-silent)
  S5  speech-to-text                (recognize_google via listen._recognize)
  S6  end-to-end listen()           (returns recognized text or "")
  S7  text-to-speech                (speak.speak via edge_tts + pygame)

Run:  .venv\\Scripts\\python.exe tools/voice_stage_test.py
Exit code 0 = every stage PASS, 1 = at least one FAIL.
"""
import os
import sys
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Match main.py/speak.py console safety so piping output can't crash prints.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

RESULTS = []


def record(stage, name, ok, detail):
    RESULTS.append((stage, name, ok, detail))
    print(f"[{stage}] {'PASS' if ok else 'FAIL'}  {name}\n"
          f"        {detail}\n", flush=True)


def stage_s1_enumerate():
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        inputs = [(i, d) for i, d in enumerate(devs) if d["max_input_channels"] > 0]
        default_in = sd.default.device[0]
        lines = [f"index={i} '{d['name']}' in={d['max_input_channels']} "
                 f"sr={d['default_samplerate']}" for i, d in inputs]
        detail = (f"sounddevice {sd.__version__}; default input index={default_in}\n"
                  "        " + "\n        ".join(lines))
        record("S1", "microphone enumeration", bool(inputs), detail)
        return bool(inputs)
    except Exception as exc:
        record("S1", "microphone enumeration", False, f"{type(exc).__name__}: {exc}")
        return False


def stage_s2_sr_microphone():
    """What listen.py's PRIMARY path does: sr.Microphone()."""
    try:
        import speech_recognition as sr
        m = sr.Microphone()
        record("S2", "sr.Microphone() (listen.py primary path)", True,
               f"PyAudio present, device_index={m.device_index}")
        return True
    except Exception as exc:
        record("S2", "sr.Microphone() (listen.py primary path)", False,
               f"{type(exc).__name__}: {exc} — PyAudio not installed; "
               f"listen.py always falls into its generic 'except Exception' branch")
        return False


def stage_s3_capture(seconds=3.0):
    try:
        import numpy as np
        import sounddevice as sd
        sr_ = 16000  # same rate listen.py's fallback uses
        rec = sd.rec(int(seconds * sr_), samplerate=sr_, channels=1,
                     dtype="int16", blocking=True)
        peak = int(np.max(np.abs(rec)))
        rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
        record("S3", "audio capture (sounddevice 16k mono int16)", True,
               f"samples={len(rec)} peak={peak} rms={rms:.1f}")
        return rec, sr_
    except Exception as exc:
        record("S3", "audio capture (sounddevice 16k mono int16)", False,
               f"{type(exc).__name__}: {exc}")
        return None, None


def stage_s4_validity(rec, sr_):
    if rec is None:
        record("S4", "captured audio validity", False, "no capture from S3")
        return None
    import numpy as np
    peak = int(np.max(np.abs(rec)))
    rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
    ok = peak > 0 and rms > 1.0
    record("S4", "captured audio validity", ok,
           f"peak={peak} rms={rms:.2f} -> {'non-silent' if ok else 'SILENT/EMPTY audio'}")
    return rec


def stage_s5_stt():
    """Feed known WAV speech to the exact STT path listen.py uses."""
    import speech_recognition as sr
    wav_path = os.path.join(ROOT, "tools", "voice_test_speech.wav")
    if not os.path.exists(wav_path):
        record("S5", "speech-to-text (recognize_google)", False,
               f"test WAV missing: {wav_path} (run tools/make_test_speech.ps1)")
        return False
    try:
        with wave.open(wav_path, "rb") as wf:
            rate, width, channels = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
            pcm = wf.readframes(wf.getnframes())
        if channels > 1:
            import numpy as np
            arr = np.frombuffer(pcm, dtype=np.int16).reshape(-1, channels).mean(axis=1)
            pcm = arr.astype(np.int16).tobytes()
        audio = sr.AudioData(pcm, sample_rate=rate, sample_width=width)
        from listen import _recognize
        t0 = time.time()
        text = _recognize(sr.Recognizer(), audio)
        dt = time.time() - t0
        ok = bool(text and text.strip())
        record("S5", "speech-to-text (recognize_google via listen._recognize)", ok,
               f"returned in {dt:.2f}s: {text!r}")
        return ok
    except Exception as exc:
        record("S5", "speech-to-text (recognize_google via listen._recognize)", False,
               f"{type(exc).__name__}: {exc}")
        return False


def stage_s6_listen_end_to_end():
    """Run listen() exactly as main.py's loop does."""
    import listen as listen_mod
    t0 = time.time()
    try:
        text = listen_mod.listen()
        dt = time.time() - t0
        record("S6", "end-to-end listen()", True,
               f"returned {text!r} in {dt:.2f}s (empty string = no speech heard "
               f"inside timeout / silence)")
        return text
    except Exception as exc:
        record("S6", "end-to-end listen()", False, f"{type(exc).__name__}: {exc}")
        return None


def stage_s7_tts():
    from speak import speak
    t0 = time.time()
    try:
        speak("This is a text to speech pipeline test.")
        dt = time.time() - t0
        import pygame
        busy = pygame.mixer.music.get_busy()
        record("S7", "text-to-speech (speak.py)", dt < 30,
               f"speak() returned in {dt:.2f}s; mixer busy flag={busy} "
               f"(audio finished playing before return is expected)")
        return True
    except Exception as exc:
        record("S7", "text-to-speech (speak.py)", False, f"{type(exc).__name__}: {exc}")
        return False


def main():
    print("=" * 78)
    print("ZYRA VOICE PIPELINE STAGE TEST")
    print("=" * 78)
    stage_s1_enumerate()
    stage_s2_sr_microphone()
    rec, sr_ = stage_s3_capture()
    stage_s4_validity(rec, sr_)
    stage_s5_stt()
    stage_s6_listen_end_to_end()
    stage_s7_tts()

    print("=" * 78)
    failed = [r for r in RESULTS if not r[2]]
    print(f"SUMMARY: {len(RESULTS) - len(failed)}/{len(RESULTS)} stages PASS")
    for stage, name, ok, _ in RESULTS:
        print(f"  {stage} {'PASS' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

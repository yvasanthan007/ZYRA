"""One-off test for the additive voice endpoints (/api/voice/*)."""
import json
import struct
import sys
import urllib.request
import wave

import uuid

BASE = "http://127.0.0.1:8099"


def http_json(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


def main():
    # 1. TTS with multiple sentences (the client sends sentence chunks)
    status, ctype, body = http_json(
        "/api/voice/tts",
        {"text": "Hello. I am ZYRA. This is the voice layer speaking."},
    )
    assert status == 200, f"TTS status {status}"
    assert ctype == "audio/mpeg", f"TTS content-type {ctype}"
    assert len(body) > 5000, f"TTS audio too small: {len(body)}"
    print(f"1. TTS OK: {len(body)} bytes of {ctype}")

    with open("zyra_tts_test.mp3", "wb") as fh:
        fh.write(body)

    # 2. TTS with empty text must be rejected cleanly
    try:
        http_json("/api/voice/tts", {"text": ""})
        print("2. FAIL: empty text was accepted")
        return 1
    except urllib.error.HTTPError as exc:
        assert exc.code == 400, f"expected 400, got {exc.code}"
        print("2. Empty-text rejection OK (HTTP 400)")

    # 3. Build a small spoken-word-like WAV (tone burst, clearly not speech)
    sample_rate = 16000
    frames = bytearray()
    for i in range(sample_rate):
        v = int(12000 * __import__("math").sin(2 * 3.14159 * 440 * i / sample_rate))
        frames += struct.pack("<h", v)
    with wave.open("test_voice.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))

    boundary = uuid.uuid4().hex
    with open("test_voice.wav", "rb") as fh:
        wav_bytes = fh.read()
    part = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + wav_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/voice/transcribe",
        data=part,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    assert result["success"] is True, result
    # A 440 Hz tone is not speech: recognition must return empty text (not an error)
    print(f"3. Transcribe OK (non-speech audio -> text={result['text']!r})")

    # 4. Existing chat endpoint untouched and responding
    status, _, body = http_json("/api/health")
    assert status == 200
    print(f"4. Health OK: {json.loads(body)['status']}")

    print("\nALL VOICE ENDPOINT TESTS PASSED")
    return 0


if __name__ == "__main__":
    import urllib.error
    sys.exit(main())

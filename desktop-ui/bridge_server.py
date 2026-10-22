import sys
import json
import importlib.util
import os
import threading
import time
import logging
# ── Windows console safety ──────────────────────────────────────────────
# Force UTF-8 stdout/stderr BEFORE importing ZYRA modules. Any emoji print
# from an imported module would otherwise raise UnicodeEncodeError on a
# cp1252 console and kill the bridge the Electron app depends on.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# Add parent directory to path for importing ZYRA modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain import ask_ai
from memory import remember, recall
from commands.open_app import (
    open_chrome, open_vscode, open_notepad, open_calculator,
    open_cmd, open_powershell, open_task_manager, open_control_panel,
    open_file_explorer, open_settings, open_google, open_youtube,
    open_github, open_chatgpt, open_gmail, open_leetcode, open_linkedin,
    search_google, search_youtube, open_downloads, open_documents,
    open_desktop, shutdown_pc, restart_pc, sleep_pc, lock_pc,
    screenshot, volume_up, volume_down, mute, wifi_on, wifi_off,
    empty_recycle_bin, current_time, current_date, play_music, open_camera,
)
from commands.close_app import close_app
from system_monitor import (
    get_system_metrics,
    format_system_monitor_text,
    get_voice_summary,
    is_system_monitor_intent,
    classify_system_query,
    answer_system_query,
    start_system_monitor,
)
# ── Voice pipeline imports (used by voice_toggle) ───────────────────────────
import speech_recognition as sr
from backend.server import process_voice_command, voice_endpoint

# Reuse the stateless speech recognizer; audio input streams are per-capture.
_voice_recognizer = None
# True while a voice_toggle capture is running on this bridge process; used
# to serialize overlapping start requests instead of opening the microphone
# twice concurrently.
_voice_capture_active = False
_voice_capture_lock = threading.Lock()
_voice_recognizer_lock = threading.Lock()
_voice_status = "Idle"
_voice_log = logging.getLogger("zyra.voice")
if not _voice_log.handlers:
    _voice_handler = logging.StreamHandler(sys.stderr)
    _voice_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _voice_log.addHandler(_voice_handler)
    _voice_log.setLevel(logging.INFO)
    _voice_log.propagate = False

def _voice_seconds(name, default):
    """Read a voice timeout from the environment (honours .env config)."""
    try:
        return max(0.5, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return float(default)


VOICE_LISTEN_TIMEOUT = _voice_seconds("ZYRA_VOICE_TIMEOUT_SECONDS", 8.0)
VOICE_PHRASE_TIMEOUT = _voice_seconds("ZYRA_VOICE_PHRASE_TIMEOUT", 12.0)
VOICE_SILENCE_SECONDS = _voice_seconds("ZYRA_VOICE_SILENCE_SECONDS", 0.8)
VOICE_MIC_DEVICE = os.environ.get("ZYRA_MIC_DEVICE", "").strip()
VOICE_MODE = (os.environ.get("ZYRA_VOICE_MODE", "google") or "google").strip().lower()

COMMAND_MAP = {
    "open_chrome": open_chrome,
    "open_vscode": open_vscode,
    "open_notepad": open_notepad,
    "open_calculator": open_calculator,
    "open_cmd": open_cmd,
    "open_powershell": open_powershell,
    "open_task_manager": open_task_manager,
    "open_control_panel": open_control_panel,
    "open_file_explorer": open_file_explorer,
    "open_settings": open_settings,
    "open_google": open_google,
    "open_youtube": open_youtube,
    "open_github": open_github,
    "open_chatgpt": open_chatgpt,
    "open_gmail": open_gmail,
    "open_leetcode": open_leetcode,
    "open_linkedin": open_linkedin,
    "open_downloads": open_downloads,
    "open_documents": open_documents,
    "open_desktop": open_desktop,
    "shutdown": shutdown_pc,
    "restart": restart_pc,
    "sleep": sleep_pc,
    "lock_pc": lock_pc,
    "screenshot": screenshot,
    "volume_up": volume_up,
    "volume_down": volume_down,
    "mute": mute,
    "wifi_on": wifi_on,
    "wifi_off": wifi_off,
    "empty_recycle_bin": empty_recycle_bin,
    "current_time": current_time,
    "current_date": current_date,
    "play_music": play_music,
    "open_camera": open_camera,
    "monitor_system": start_system_monitor,
    "system_monitor": start_system_monitor,
}


def _capture_voice_audio(recognizer):
    """
    Capture speech with sounddevice, without requiring the PyAudio backend.

    Runs the stream in a dedicated thread with a hard wall-clock deadline
    (VOICE_LISTEN_TIMEOUT + small buffer) so the microphone is ALWAYS released
    on completion, timeout, or exception. Never leaves a capture in flight.
    """
    import numpy as np
    import sounddevice as sd
    from concurrent.futures import ThreadPoolExecutor
    sample_rate = 16000
    block_size = 1600  # 100 ms chunks for responsive endpointing
    device = int(VOICE_MIC_DEVICE) if VOICE_MIC_DEVICE.isdigit() else (VOICE_MIC_DEVICE or None)
    deadline = time.monotonic() + (VOICE_LISTEN_TIMEOUT + VOICE_PHRASE_TIMEOUT + 2.0)

    def _run():
        frames = []
        started_at = time.monotonic()
        speech_started_at = None
        last_voice_at = None
        stream = None
        try:
            stream = sd.InputStream(
                samplerate=sample_rate, channels=1, dtype="int16", blocksize=block_size,
                device=device, latency="low"
            )
            stream.start()
            noise_levels = []
            for _ in range(3):
                block, overflowed = stream.read(block_size)
                if overflowed:
                    _voice_log.warning("microphone overflow during ambient calibration")
                noise_levels.append(float(np.sqrt(np.mean(np.square(block.astype(np.float32))))))
            noise_floor = sorted(noise_levels)[len(noise_levels) // 2]
            threshold = max(180.0, min(1400.0, noise_floor * 2.2))

            listen_deadline = started_at + VOICE_LISTEN_TIMEOUT
            while time.monotonic() < (listen_deadline if speech_started_at is None else min(deadline, speech_started_at + VOICE_PHRASE_TIMEOUT)):
                # Respect the hard deadline so a hung stream can never hold the
                # microphone open. We still call stream.read exactly once per
                # loop so we never busy-spin or starve the audio thread.
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                block, overflowed = stream.read(block_size, timeout=min(0.15, remaining))
                if overflowed:
                    _voice_log.warning("microphone input overflow during capture")
                now = time.monotonic()
                level = float(np.sqrt(np.mean(np.square(block.astype(np.float32)))))
                if level >= threshold:
                    if speech_started_at is None:
                        speech_started_at = now
                    last_voice_at = now
                    frames.append(block.copy())
                elif speech_started_at is not None:
                    frames.append(block.copy())
                    if now - last_voice_at >= VOICE_SILENCE_SECONDS:
                        break
                if (speech_started_at is not None and
                        now - speech_started_at >= VOICE_PHRASE_TIMEOUT):
                    break
            return frames
        finally:
            if stream is not None:
                try:
                    if stream.is_active():
                        stream.stop()
                finally:
                    stream.close()

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zyra-mic")
    future = pool.submit(_run)
    try:
        frames = future.result(timeout=VOICE_LISTEN_TIMEOUT + VOICE_PHRASE_TIMEOUT + 2.0)
    except Exception as exc:
        future.cancel()
        raise RuntimeError(f"Microphone capture failed: {type(exc).__name__}: {exc}") from exc
    finally:
        # Do not wait for an audio driver that ignored its read timeout.
        pool.shutdown(wait=False, cancel_futures=True)

    if not frames:
        return None
    pcm = np.concatenate(frames, axis=0).reshape(-1).astype(np.int16).tobytes()
    return sr.AudioData(pcm, sample_rate, sample_width=2)


def handle_message(msg):
    msg_type = msg.get("type", "")
    data = msg.get("data")

    # ── URL resolution helper (shared by analyze_link paths) ──
    def _resolve_link_target(explicit_url=None, text=None):
        """Resolve which URL to analyze: explicit > text-embedded > capture.

        Returns (target_url, source) where source is one of
        "selected" | "entered" | "message" | "screen" | "none".

        Privacy: callers must only log whether a URL was received and its
        source - never clipboard/screen contents.
        """
        from backend.link_security import extract_url as _extract

        candidate = (explicit_url or "").strip() if explicit_url else ""
        if candidate:
            return candidate, "selected"
        if text and text.strip():
            found = _extract(text)
            if found:
                return found, "message"
        return None, "none"

    def _call_with_timeout(func, timeout, *args, **kwargs):
        """Run optional capture work without waiting for its worker thread."""
        finished = threading.Event()
        outcome = {}

        def _worker():
            try:
                outcome["result"] = func(*args, **kwargs)
            except Exception as exc:
                outcome["error"] = exc
            finally:
                finished.set()

        threading.Thread(target=_worker, daemon=True,
                         name="ZYRA-bounded-capture").start()
        if not finished.wait(timeout):
            raise TimeoutError("capture timed out")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("result")

    if msg_type == "analyze_link":
        # Selected/entered-URL phishing analysis for the desktop UI.
        # Contract: data may be a raw URL string or
        # {url, text?, timeout_secs?}. An explicitly provided URL is
        # analyzed DIRECTLY — screen OCR is only a fallback when no URL
        # was passed, and it runs bounded off-thread so the shared bridge
        # (and any active voice session) is never blocked.

        explicit_url = None
        fallback_text = None
        allow_capture_fallback = True
        ocr_timeout = 12.0
        if isinstance(data, str):
            explicit_url = data.strip()
        elif isinstance(data, dict):
            explicit_url = str(data.get("url") or "").strip()
            fallback_text = data.get("text")
            allow_capture_fallback = bool(data.get("capture_fallback", False))
            try:
                ocr_timeout = max(2.0, min(30.0, float(
                    data.get("timeout_secs", ocr_timeout))))
            except (TypeError, ValueError):
                ocr_timeout = 12.0
        else:
            return {"success": False, "error": "Invalid analyze_link data"}
        # Privacy-conscious diagnostic: event + URL presence only.
        print(f"[analyze_link] event=received "
              f"has_explicit_url={bool(explicit_url)}")
        target, source = _resolve_link_target(explicit_url, fallback_text)
        if target:
            print(f"[analyze_link] source={source} "
                  f"has_url=True url_len={len(target)}")
        elif allow_capture_fallback:
            print("[analyze_link] source=none has_url=False; "
                  "falling back to screen/clipboard capture")
            try:
                from screen_ocr import get_active_url as _capture_url
                target = _call_with_timeout(_capture_url, ocr_timeout)
                target = target.strip() if isinstance(target, str) else None
                source = "screen" if target else "none"
                print(f"[analyze_link] capture done source={source} "
                      f"has_url={bool(target)}")
            except TimeoutError:
                print(f"[analyze_link] OCR capture timed out after "
                      f"{ocr_timeout}s; reporting no-URL (voice unaffected)")
                return {"success": False,
                        "error": "Screen/clipboard URL capture timed out.",
                        "source": "none"}
            except Exception as exc:
                print(f"[analyze_link] capture error "
                      f"({type(exc).__name__}); reporting no-URL")
                return {"success": False,
                        "error": f"Screen/clipboard URL capture failed ({type(exc).__name__}).",
                        "source": "none"}
        if not target:
            return {
                "success": False,
                "error": ("No URL was provided. Enter or select a URL, "
                          "or ensure a link is visible on screen/in clipboard."),
                "source": "none",
            }
        # Validate + analyze the resolved URL directly (never auto-open).
        try:
            import sys as _sys
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _root not in _sys.path:
                _sys.path.insert(0, _root)
            from link_analysis import analyze_url as _analyze
        except Exception as exc:
            return {"success": False,
                    "error": f"Analysis engine unavailable ({type(exc).__name__}).",
                    "source": source, "url": target}
        from backend.link_security import extract_url as _normalize_check
        checked = _normalize_check(target) or target.strip()
        print(f"[analyze_link] analyzing source={source} "
              f"url_len={len(checked)}")
        try:
            result = _analyze(checked)
        except Exception as exc:
            return {"success": False,
                    "error": f"Analysis failed ({type(exc).__name__}).",
                    "source": source, "url": checked}
        result["source"] = source
        result["url"] = checked
        return {"success": True, "data": result}

    elif msg_type == "chat":
        if isinstance(data, str):
            # Route through the same backend bridge as the dashboard so link
            # security (now ML-fused), system monitor, DNS and nmap intents
            # behave identically everywhere and plain chat reaches Ollama.
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from backend.zyra_bridge import process_chat as _bridge_chat
                answer = _bridge_chat(data)
            except Exception:
                if is_system_monitor_intent(data):
                    # Answered locally from live metrics: metric questions get a
                    # focused answer, an explicit monitor request gets the card.
                    return {
                        "success": True,
                        "data": answer_system_query(data),
                        "monitor_topic": classify_system_query(data) or "overall",
                    }
                answer = ask_ai(data)
            return {"success": True, "data": answer}
        return {"success": False, "error": "Invalid chat data"}

    elif msg_type == "command":
        if isinstance(data, str):
            command_name = data
            if command_name in COMMAND_MAP:
                result = COMMAND_MAP[command_name]()
                return {"success": True, "data": f"Executed {command_name}"}
            elif "close_" in command_name or command_name.startswith("search_"):
                # Handle search and close commands differently
                return {"success": True, "data": f"Command {command_name} not directly supported via UI action"}
            return {"success": False, "error": f"Unknown command: {command_name}"}
        return {"success": False, "error": "Invalid command data"}

    elif msg_type == "remember":
        if isinstance(data, dict):
            key = data.get("key")
            value = data.get("value")
            remember(key, value)
            return {"success": True, "data": f"Remembered {key}"}
        return {"success": False, "error": "Invalid remember data"}

    elif msg_type == "recall":
        if isinstance(data, str):
            value = recall(data)
            return {"success": True, "data": value}
        return {"success": False, "error": "Invalid recall data"}

    elif msg_type == "voice_toggle":
        # Zyra voice toggle: capture STT audio, run speech-to-text, forward the
        # transcribed text to the existing backend voice endpoint, and return
        # { transcript, response } to the UI so VoiceControl.setTranscript and
        # VoiceControl.setResponse are driven from a single place.
        #
        # The backend voice endpoint is the existing FastAPI Pipeline:
        #   backend/server.py process_voice_command() -> { response, action }
        # This keeps the message-routing path consistent with the WebSocket
        # /ws 'voice' type and the /api/voice endpoint rather than creating a
        # second voice architecture. NOTE: /api/voice accepts transcribed
        # TEXT only — microphone capture lives here in the bridge.
        #
        # Lifecycle: Idle -> Listening -> Recognizing -> Processing ->
        # Response displayed -> Idle. The capture is synchronous and blocking,
        # so an in-flight listen CANNOT be cancelled mid-call by flipping the
        # UI toggle — Electron serializes stop requests behind it (see
        # desktop-ui/src/main/main.ts voice:toggle). Overlapping start
        # requests are rejected here instead of opening the mic twice.
        # `data=false` (stop when idle) never opens the microphone.
        if isinstance(data, bool) and not data:
            return {
                "success": True,
                "data": {"transcript": "", "response": "", "listening": False},
            }

        global _voice_capture_active, _voice_status
        request_started = time.monotonic()
        request_id = f"voice-{int(time.time() * 1000)}"
        request_logged = False
        if not _voice_capture_lock.acquire(blocking=False):
            _voice_log.warning("request=%s stage=mic rejected reason=capture_in_progress", request_id)
            return {
                "success": False,
                "error": "Voice capture already in progress. Wait for it to finish.",
            }
        _voice_capture_active = True
        _voice_status = "Listening"
        _voice_log.info("request=%s stage=mic status=started", request_id)
        # Use one bounded sounddevice input stream per request. Unlike
        # sr.Microphone(), this path does not require PyAudio, which is often
        # absent in Windows installations and packaged environments.
        global _voice_recognizer
        try:
            if _voice_recognizer is None:
                _voice_recognizer = sr.Recognizer()
            capture_started = time.monotonic()
            audio = _capture_voice_audio(_voice_recognizer)
            _voice_log.info("request=%s stage=vad_capture duration=%.3fs result=%s", request_id, time.monotonic() - capture_started, "audio" if audio is not None else "silence")
            if audio is None:
                _voice_status = "Idle"
                _voice_log.warning("request=%s stage=vad_capture empty_transcript total=%.3fs", request_id, time.monotonic() - request_started)
                return {
                    "success": True,
                    "data": {
                        "transcript": "",
                        "response": "No speech detected before the timeout. Please try again.",
                    },
                }
            from listen import _recognize as _recognize_audio
            _voice_status = "Processing"
            stt_started = time.monotonic()
            with _voice_recognizer_lock:
                text = _recognize_audio(_voice_recognizer, audio).strip()
            _voice_log.info("request=%s stage=stt duration=%.3fs transcript_chars=%d", request_id, time.monotonic() - stt_started, len(text))
        except sr.WaitTimeoutError:
            _voice_status = "Idle"
            _voice_log.warning("request=%s stage=stt timeout duration=%.3fs", request_id, time.monotonic() - request_started)
            return {
                "success": True,
                "data": {
                    "transcript": "",
                    "response": "No speech detected before the timeout. Please try again.",
                },
            }
        except sr.UnknownValueError:
            # No speech detected — surface an explicit, non-fatal result.
            _voice_status = "Idle"
            _voice_log.warning("request=%s stage=stt empty_transcript duration=%.3fs", request_id, time.monotonic() - request_started)
            return {
                "success": True,
                "data": {
                    "transcript": "",
                    "response": "I didn't catch that. Please speak louder or try again.",
                },
            }
        except sr.RequestError as exc:
            _voice_status = "Idle"
            _voice_log.error("request=%s stage=stt request_error duration=%.3fs error=%s", request_id, time.monotonic() - request_started, exc)
            # Keep errors in the success payload: the desktop bridge protocol
            # rejects failures before its structured data reaches the renderer.
            return {
                "success": True,
                "data": {
                    "transcript": "",
                    "response": f"STT unavailable: {exc}. Check network connectivity and try again.",
                    "error": f"STT unavailable: {exc}",
                },
            }
        except Exception as exc:
            _voice_status = "Error"
            _voice_log.exception("request=%s stage=mic_or_stt exception=%s duration=%.3fs", request_id, type(exc).__name__, time.monotonic() - request_started)
            return {
                "success": True,
                "data": {
                    "transcript": "",
                    "response": f"Voice capture error: {exc}",
                    "error": f"Voice capture error: {exc}",
                },
            }
        finally:
            _voice_capture_active = False
            _voice_capture_lock.release()
        if not text:
            _voice_status = "Idle"
            _voice_log.warning("request=%s stage=stt empty_transcript total=%.3fs", request_id, time.monotonic() - request_started)
            return {
                "success": True,
                "data": {"transcript": "", "response": "I didn't catch that. Please try again."},
            }

        # Forward recognized speech through the existing intent router.
        try:
            _voice_status = "Processing"
            _voice_log.info("request=%s stage=intent status=started transcript_chars=%d", request_id, len(text))
            intent_started = time.monotonic()
            result = process_voice_command(text)
            _voice_log.info("request=%s stage=intent_backend duration=%.3fs action=%s", request_id, time.monotonic() - intent_started, result.get("action", "unknown") if isinstance(result, dict) else "unknown")
        except Exception as exc:
            _voice_status = "Error"
            _voice_log.exception("request=%s stage=intent_backend exception=%s duration=%.3fs", request_id, type(exc).__name__, time.monotonic() - request_started)
            return {
                "success": False,
                "data": {
                    "transcript": text,
                    "response": f"Voice backend error: {exc}",
                },
            }

        transcript = text
        response = result.get("response", "") if isinstance(result, dict) else ""
        _voice_status = "Idle"
        _voice_log.info("request=%s stage=response_generation total=%.3fs response_chars=%d", request_id, time.monotonic() - request_started, len(response))
        if response:
            return {
                "success": True,
                "data": {"transcript": transcript, "response": response},
            }

        _voice_log.warning("request=%s stage=response empty_response total=%.3fs", request_id, time.monotonic() - request_started)
        return {
            "success": True,
            "data": {
                "transcript": transcript,
                "response": "(Zyra has nothing to say for this command.)",
            },
        }

    elif msg_type == "voice_stop":
        # Idempotent stand-down: never opens the microphone. Reports whether
        # a capture is still running so the UI can show honest state.
        return {"success": True, "data": {"listening": bool(_voice_capture_active)}}

    elif msg_type == "voice_status":
        return {"success": True, "data": {"listening": bool(_voice_capture_active), "status": _voice_status}}

    elif msg_type in ("system_metrics", "get_system_metrics", "monitor_system"):
        metrics = get_system_metrics()
        return {
            "success": True,
            "data": metrics,
            "formatted": format_system_monitor_text(metrics),
            "summary": get_voice_summary(metrics),
        }

    return {"success": False, "error": f"Unknown type: {msg_type}"}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = None
        try:
            msg = json.loads(line)
            msg_id = msg.get("id")
            response = handle_message(msg)
            response["id"] = msg_id
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            _voice_log.exception("bridge request failed type=%s", (msg.get("type") if isinstance(msg, dict) else "invalid"))
            sys.stdout.write(
                json.dumps({"id": (msg.get("id", 0) if isinstance(msg, dict) else 0), "success": False, "error": str(e)}) + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()

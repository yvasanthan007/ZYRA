import sys
import json
import importlib.util
import os

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

# Cache so repeated voice toggles re-use a single Recognizer + Microphone.
_voice_recognizer = None
_voice_microphone = None

VOICE_LISTEN_TIMEOUT = 8.0   # seconds before we stop listening for silence
VOICE_PHRASE_TIMEOUT = 0.75  # seconds of silence to end an utterance

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


def handle_message(msg):
    msg_type = msg.get("type", "")
    data = msg.get("data")

    if msg_type == "chat":
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
        # second voice architecture.

        # Use the cached Recognizer/Microphone, creating them on first use.
        global _voice_recognizer, _voice_microphone
        if _voice_recognizer is None:
            _voice_recognizer = sr.Recognizer()
        if _voice_microphone is None:
            _voice_microphone = sr.Microphone()

        try:
            # Capture a short audio segment (the UI drives the toggle; the
            # bridge captures until silence or the timeout).
            with _voice_microphone as source:
                _voice_recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = _voice_recognizer.listen(
                    source,
                    timeout=VOICE_LISTEN_TIMEOUT,
                    phrase_time_limit=VOICE_LISTEN_TIMEOUT,
                )

            # Run speech-to-text. Google STT is the default; if it is
            # unavailable, surface the failure explicitly instead of
            # silently dropping the utterance.
            text = _voice_recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            # No speech detected — surface an explicit, non-fatal result.
            return {
                "success": True,
                "data": {
                    "transcript": "",
                    "response": "I didn't catch that. Please speak louder or try again.",
                },
            }
        except sr.RequestError as exc:
            # STT service unavailable (e.g. no network) — fail explicitly.
            return {
                "success": False,
                "data": {
                    "transcript": "",
                    "response": f"STT unavailable: {exc}. Check network connectivity and try again.",
                },
            }
        except Exception as exc:
            return {
                "success": False,
                "data": {
                    "transcript": "",
                    "response": f"Voice capture error: {exc}",
                },
            }

        if not text:
            return {
                "success": True,
                "data": {"transcript": "", "response": "I didn't catch that. Please try again."},
            }

        # Forward the recognized text to the existing backend voice endpoint
        # (backend/server.py process_voice_command), which is the same
        # function /api/voice and the WebSocket 'voice' type use.
        try:
            result = process_voice_command(text)
        except Exception as exc:
            return {
                "success": False,
                "data": {
                    "transcript": text,
                    "response": f"Voice backend error: {exc}",
                },
            }

        transcript = text
        response = result.get("response", "") if isinstance(result, dict) else ""
        if response:
            return {
                "success": True,
                "data": {"transcript": transcript, "response": response},
            }

        return {
            "success": True,
            "data": {
                "transcript": transcript,
                "response": "(Zyra has nothing to say for this command.)",
            },
        }

    elif msg_type == "voice_status":
        return {"success": True, "data": {"listening": False}}

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
        try:
            msg = json.loads(line)
            msg_id = msg.get("id")
            response = handle_message(msg)
            response["id"] = msg_id
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            sys.stdout.write(
                json.dumps({"id": 0, "success": False, "error": str(e)}) + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()

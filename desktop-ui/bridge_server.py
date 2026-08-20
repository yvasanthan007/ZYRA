import sys
import json
import importlib.util
import os

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
}


def handle_message(msg):
    msg_type = msg.get("type", "")
    data = msg.get("data")

    if msg_type == "chat":
        if isinstance(data, str):
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
        # Voice toggle is handled by the UI; this is a placeholder
        return {"success": True, "data": "Voice toggled"}

    elif msg_type == "voice_status":
        return {"success": True, "data": {"listening": False}}

    elif msg_type == "speak":
        if isinstance(data, str):
            from speak import speak
            speak(data)
            return {"success": True, "data": "Speaking..."}
        return {"success": False, "error": "Invalid speak data"}

    elif msg_type == "analyze_link":
        # Link security analysis via the bridge
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            text = data.get("url") or data.get("text") or ""
        else:
            return {"success": False, "error": "Invalid analyze_link data"}

        if not text:
            return {"success": False, "error": "No URL provided"}

        from backend.link_security import extract_url, analyze_url_security, format_security_report
        url = extract_url(text)
        if not url:
            return {"success": False, "error": "No URL found to analyze"}

        result = analyze_url_security(url)
        return {"success": True, "data": {
            "report": format_security_report(result),
            "analysis": result,
        }}

    elif msg_type == "list_commands":
        return {"success": True, "data": list(COMMAND_MAP.keys())}

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

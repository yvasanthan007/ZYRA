"""
Zyra Bridge Module
Bridges FastAPI backend with Zyra's AI modules (brain, speak, listen, commands)
"""
import sys
import os
import json
import threading
from typing import Optional, Dict, Any

# Ensure parent directory is in path to import Zyra modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain import ask_ai
from speak import speak
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
    start_system_monitor,
)

# ── Backend Security Analysis Module (backend-only, no frontend UI) ──
from backend.link_security import (
    is_link_analysis_request,
    analyze_link_request,
    analyze_url_security,
    format_security_report,
    summarize_for_voice,
    extract_url,
)

# ── DNS Lookup Module (real DNS intelligence via dnspython) ──
from backend.dns_lookup import (
    build_chat_ack as dns_build_chat_ack,
    is_dns_intent,
    extract_dns_target,
)

# ── Nmap Network Scanner Module (backend service layer) ──
from backend.nmap_service import (
    is_nmap_intent,
    resolve_operation,
    extract_target,
    validate_target,
    run_scan,
    nmap_available,
    build_nmap_command,
)

# ── "Scan My Network" (real-time local subnet host discovery) ──
from backend.network_scan import (
    is_network_scan_intent,
    scan_my_network,
)

# Command map for executing voice commands programmatically
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
    "search_google": search_google,
    "search_youtube": search_youtube,
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

# Keep track of the voice assistant thread
_voice_thread: Optional[threading.Thread] = None
_voice_running = False


def _nmap_starting_message(text: str) -> str:
    """
    Build a concise chat/voice response for an Nmap scanning request.

    The scan itself is executed asynchronously by the server (which broadcasts
    live status + results to the Nmap Scanner panel), so this just confirms
    what Zyra is about to do.
    """
    op_key, op = resolve_operation(text)
    target = extract_target(text) or op.get("default_target", "127.0.0.1")
    valid, msg = validate_target(target)
    if not valid:
        return f"I couldn't use that target. {msg}"
    return (
        f"Running a {op['label']} scan on {target}. I'll show the live results "
        f"in the Nmap Scanner panel when it completes."
    )


def process_chat(message: str) -> str:
    """
    Process a chat message through Zyra's AI brain.

    Args:
        message: The user's message/query

    Returns:
        Zyra's response as a string
    """
    if not message or not message.strip():
        return "Please say something!"

    # ── Backend-only link security analysis ──
    # When the user provides a link or triggers analysis, return the structured
    # text-only security report directly — no frontend/dashboard UI changes.
    if is_link_analysis_request(message):
        return analyze_link_request(message)

    # ── System Monitor ──
    if is_system_monitor_intent(message):
        return format_system_monitor_text()

    # ── DNS Lookup ──
    # Intent detection is handled here; the actual lookup runs in the server
    # (background thread) which then broadcasts the DNS Lookup panel + live
    # progress. The acknowledgement keeps ZYRA from hallucinating DNS data.
    if is_dns_intent(message):
        target = extract_dns_target(message)
        return dns_build_chat_ack(target)

    # ── "Scan My Network" (real-time local subnet host discovery) ──
    # Typed and spoken requests both land here. The shared scan function
    # detects the local private IPv4/subnet, validates it and runs
    # `nmap -sn <subnet>` — the FULL results are returned directly inside
    # the existing chat, so ZYRA never hallucinates network data.
    if is_network_scan_intent(message):
        return scan_my_network().get(
            "chat_response",
            "The network scan could not be completed.",
        )

    # ── Nmap Network Scanner ──
    # Intent detection is handled by the backend; the actual scan runs in the
    # server (background thread) which then broadcasts the Nmap Scanner panel.
    if is_nmap_intent(message):
        return _nmap_starting_message(message)

    answer = ask_ai(message)
    return answer


def process_command(command_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute a voice command programmatically.

    Args:
        command_name: The command to execute (e.g., "open_chrome")
        params: Optional parameters for the command

    Returns:
        Result dict with success status and message
    """
    if not command_name:
        return {"success": False, "error": "No command specified"}

    command_name = command_name.lower().strip()

    # Handle close commands
    if command_name.startswith("close_"):
        app_name = command_name.replace("close_", "").strip()
        response = close_app(app_name)
        return {"success": True, "data": response}

    # Handle search commands
    if command_name.startswith("search_google"):
        query = params.get("query", "") if params else ""
        if query:
            search_google(query)
            return {"success": True, "data": f"Searched Google for {query}"}
        return {"success": False, "error": "No search query provided"}

    if command_name.startswith("search_youtube"):
        query = params.get("query", "") if params else ""
        if query:
            search_youtube(query)
            return {"success": True, "data": f"Searched YouTube for {query}"}
        return {"success": False, "error": "No search query provided"}

    # Execute from command map
    if command_name in COMMAND_MAP:
        try:
            result = COMMAND_MAP[command_name]()
            return {"success": True, "data": f"Executed {command_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"success": False, "error": f"Unknown command: {command_name}"}


def process_voice_command(transcribed_text: str) -> Dict[str, Any]:
    """
    Process a voice command from transcribed text.
    Parses natural language and executes the appropriate action.

    Args:
        transcribed_text: The text transcribed from voice

    Returns:
        Result dict with response text and action taken
    """
    if not transcribed_text:
        return {"response": "", "action": "none"}

    text = transcribed_text.lower().strip()

    # Check for close commands
    if text.startswith("close "):
        app = text.replace("close ", "").strip()
        response = close_app(app)
        return {"response": response, "action": "close_app"}

    # Check for memory commands
    if "my favorite language is" in text:
        language = text.replace("my favorite language is", "").strip()
        remember("favorite_language", language)
        return {
            "response": f"I'll remember that. Your favorite language is {language}.",
            "action": "remember"
        }

    if "what is my favorite language" in text:
        language = recall("favorite_language")
        if language:
            return {"response": f"Your favorite language is {language}.", "action": "recall"}
        return {"response": "I don't know your favorite language yet.", "action": "recall"}

    # Check for exit commands
    if any(word in text for word in ["exit", "quit", "goodbye", "shut it down"]):
        return {"response": "Goodbye. Have a nice day.", "action": "exit"}

    # ── Backend-only link security analysis ──
    # Activated by "Analyse the link" / "Analyze this URL" or any URL in text.
    if is_link_analysis_request(text):
        return {"response": analyze_link_request(text), "action": "link_analysis"}

    # ── System Monitor intent ──
    if is_system_monitor_intent(text):
        metrics = get_system_metrics()
        voice_resp = get_voice_summary(metrics)
        return {
            "response": voice_resp,
            "action": "system_monitor",
            "metrics": metrics,
            "formatted": format_system_monitor_text(metrics),
        }

    # ── DNS Lookup intent ──
    # The actual lookup is executed by the server in a background thread,
    # which then broadcasts live status + results to the DNS Lookup panel.
    if is_dns_intent(text):
        target = extract_dns_target(text)
        return {
            "response": dns_build_chat_ack(target),
            "action": "dns_lookup",
            "dns_request": text,
        }

    # ── Nmap Network Scanner intent ──
    # The actual scan is executed by the server in a background thread, which
    # then broadcasts live status + results to the Nmap Scanner panel.
    if is_nmap_intent(text):
        return {
            "response": _nmap_starting_message(text),
            "action": "nmap_scan",
            "nmap_request": text,
        }

    # Check command map (natural language matching)
    command_mappings = [
        ("open chrome", "open_chrome"),
        ("open vscode", "open_vscode"),
        ("open visual studio code", "open_vscode"),
        ("open notepad", "open_notepad"),
        ("open calculator", "open_calculator"),
        ("open cmd", "open_cmd"),
        ("open command prompt", "open_cmd"),
        ("open powershell", "open_powershell"),
        ("open task manager", "open_task_manager"),
        ("open control panel", "open_control_panel"),
        ("open file explorer", "open_file_explorer"),
        ("open explorer", "open_file_explorer"),
        ("open settings", "open_settings"),
        ("open google", "open_google"),
        ("open youtube", "open_youtube"),
        ("open github", "open_github"),
        ("open chatgpt", "open_chatgpt"),
        ("open gmail", "open_gmail"),
        ("open leetcode", "open_leetcode"),
        ("open linkedin", "open_linkedin"),
        ("open downloads", "open_downloads"),
        ("open documents", "open_documents"),
        ("open desktop", "open_desktop"),
        ("open camera", "open_camera"),
        ("shutdown", "shutdown"),
        ("restart", "restart"),
        ("sleep", "sleep"),
        ("lock", "lock_pc"),
        ("screenshot", "screenshot"),
        ("volume up", "volume_up"),
        ("volume down", "volume_down"),
        ("mute", "mute"),
        ("turn on wifi", "wifi_on"),
        ("turn off wifi", "wifi_off"),
        ("empty recycle bin", "empty_recycle_bin"),
        ("current time", "current_time"),
        ("what is the time", "current_time"),
        ("today's date", "current_date"),
        ("current date", "current_date"),
        ("play music", "play_music"),
    ]

    for phrase, command in command_mappings:
        if phrase in text:
            try:
                COMMAND_MAP[command]()
                # Get friendly response based on command
                responses = {
                    "open_chrome": "Opening Chrome",
                    "open_vscode": "Opening Visual Studio Code",
                    "open_notepad": "Opening Notepad",
                    "open_calculator": "Opening Calculator",
                    "open_cmd": "Opening Command Prompt",
                    "open_powershell": "Opening PowerShell",
                    "open_task_manager": "Opening Task Manager",
                    "open_control_panel": "Opening Control Panel",
                    "open_file_explorer": "Opening File Explorer",
                    "open_settings": "Opening Settings",
                    "open_google": "Opening Google",
                    "open_youtube": "Opening YouTube",
                    "open_github": "Opening GitHub",
                    "open_chatgpt": "Opening ChatGPT",
                    "open_gmail": "Opening Gmail",
                    "open_leetcode": "Opening LeetCode",
                    "open_linkedin": "Opening LinkedIn",
                    "open_downloads": "Opening Downloads",
                    "open_documents": "Opening Documents",
                    "open_desktop": "Opening Desktop",
                    "open_camera": "Opening Camera",
                    "shutdown": "Shutting down the PC",
                    "restart": "Restarting the PC",
                    "sleep": "Putting the PC to sleep",
                    "lock_pc": "Locking the PC",
                    "screenshot": "Taking a screenshot",
                    "volume_up": "Increasing volume",
                    "volume_down": "Decreasing volume",
                    "mute": "Muting volume",
                    "wifi_on": "Turning on Wi-Fi",
                    "wifi_off": "Turning off Wi-Fi",
                    "empty_recycle_bin": "Emptying the Recycle Bin",
                    "current_time": "Fetching current time",
                    "current_date": "Fetching current date",
                    "play_music": "Playing music",
                }
                response_text = responses.get(command, f"Executing {command}")
                return {"response": response_text, "action": command}
            except Exception as e:
                return {"response": f"Error executing command: {str(e)}", "action": "error"}

    # For search commands
    if "search google for" in text:
        query = text.replace("search google for", "").strip()
        search_google(query)
        return {"response": f"Searching Google for {query}", "action": "search_google"}

    if "search youtube for" in text:
        query = text.replace("search youtube for", "").strip()
        search_youtube(query)
        return {"response": f"Searching YouTube for {query}", "action": "search_youtube"}

    # Default: use AI brain
    answer = ask_ai(text)
    return {"response": answer, "action": "chat"}


def speak_text(text: str) -> None:
    """
    Speak text using Zyra's TTS engine.
    Runs in a separate thread to not block the API.
    """
    if not text:
        return

    thread = threading.Thread(target=speak, args=(text,), daemon=True)
    thread.start()


# Convenience functions that match the existing pattern
def process_message(message_type: str, data: Any) -> Dict[str, Any]:
    """
    Unified message processing for the bridge.
    Compatible with the existing bridge_server.py pattern.
    """
    if message_type == "chat":
        if isinstance(data, str):
            answer = process_chat(data)
            return {"success": True, "data": answer}
        return {"success": False, "error": "Invalid chat data"}

    elif message_type == "command":
        if isinstance(data, str):
            result = process_command(data)
            return result
        elif isinstance(data, dict):
            result = process_command(data.get("command", ""), data)
            return result
        return {"success": False, "error": "Invalid command data"}

    elif message_type == "voice":
        if isinstance(data, str):
            result = process_voice_command(data)
            return {"success": True, "data": result}
        return {"success": False, "error": "Invalid voice data"}

    elif message_type == "remember":
        if isinstance(data, dict):
            key = data.get("key")
            value = data.get("value")
            remember(key, value)
            return {"success": True, "data": f"Remembered {key}"}
        return {"success": False, "error": "Invalid remember data"}

    elif message_type == "recall":
        if isinstance(data, str):
            value = recall(data)
            return {"success": True, "data": value}
        return {"success": False, "error": "Invalid recall data"}

    elif message_type == "speak":
        if isinstance(data, str):
            speak_text(data)
            return {"success": True, "data": "Speaking"}
        return {"success": False, "error": "Invalid speak data"}

    elif message_type == "analyze_link":
        # Backend-only link security analysis via the bridge.
        # data may be a raw URL string, a message containing a URL, or a dict
        # with {"url": ...} / {"text": ...}.
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            text = data.get("url") or data.get("text") or ""
        else:
            return {"success": False, "error": "Invalid analyze_link data"}
        url = extract_url(text) if text else None
        if not url:
            return {"success": False, "error": "No URL found to analyze"}
        result = analyze_url_security(url)
        return {"success": True, "data": {
            "report": format_security_report(result),
            "analysis": result,
        }}

    elif message_type in ("system_metrics", "get_system_metrics", "monitor_system", "start_monitoring"):
        metrics = get_system_metrics()
        return {
            "success": True,
            "data": metrics,
            "formatted": format_system_monitor_text(metrics),
            "summary": get_voice_summary(metrics),
        }

    elif message_type == "nmap_status":
        # Report whether Nmap is installed + list available scan operations.
        status = nmap_available()
        return {
            "success": True,
            "data": {
                "available": status.get("available", False),
                "version": status.get("version", "unknown"),
                "error": status.get("error"),
            },
        }

    return {"success": False, "error": f"Unknown type: {message_type}"}

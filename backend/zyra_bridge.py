"""
Zyra Bridge Module
Connects Zyra's FastAPI backend to CyberLLM, voice, memory,
security analysis, system monitoring, DNS, Nmap and Windows commands.

Normal conversational AI requests are routed through CyberLLM.
Speech dependencies are optional so text chat can work without pygame.
"""

import os
import sys
import threading
from typing import Optional, Dict, Any


# ============================================================
# PATH CONFIGURATION
# ============================================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# MEMORY
# ============================================================

from memory import remember, recall


# ============================================================
# OPTIONAL SPEECH SUPPORT
# ============================================================

_SPEECH_AVAILABLE = False

try:
    from speak import speak, stop_speaking
    _SPEECH_AVAILABLE = True

except Exception as exc:
    print(
        "[Zyra/Speech] Speech module unavailable: "
        f"{type(exc).__name__}: {exc}"
    )

    def speak(*args, **kwargs):
        print("[Zyra/Speech] Text-to-speech is unavailable.")

    def stop_speaking(*args, **kwargs):
        return None


# ============================================================
# WINDOWS COMMANDS
# ============================================================

from commands.open_app import (
    open_chrome,
    open_vscode,
    open_notepad,
    open_calculator,
    open_cmd,
    open_powershell,
    open_task_manager,
    open_control_panel,
    open_file_explorer,
    open_settings,
    open_google,
    open_youtube,
    open_github,
    open_chatgpt,
    open_gmail,
    open_leetcode,
    open_linkedin,
    search_google,
    search_youtube,
    open_downloads,
    open_documents,
    open_desktop,
    shutdown_pc,
    restart_pc,
    sleep_pc,
    lock_pc,
    screenshot,
    volume_up,
    volume_down,
    mute,
    wifi_on,
    wifi_off,
    empty_recycle_bin,
    current_time,
    current_date,
    play_music,
    open_camera,
)

from commands.close_app import close_app


# ============================================================
# SYSTEM MONITORING
# ============================================================

from system_monitor import (
    get_system_metrics,
    format_system_monitor_text,
    get_voice_summary,
    is_system_monitor_intent,
    classify_system_query,
    answer_system_query,
    start_system_monitor,
)


# ============================================================
# LINK SECURITY
# ============================================================

from backend.link_security import (
    is_link_analysis_request,
    analyze_link_request,
    analyze_url_security,
    format_security_report,
    summarize_for_voice,
    extract_url,
)


# ============================================================
# DNS
# ============================================================

from backend.dns_lookup import (
    build_chat_ack as dns_build_chat_ack,
    is_dns_intent,
    extract_dns_target,
)


# ============================================================
# NMAP
# ============================================================

from backend.nmap_service import (
    is_nmap_intent,
    resolve_operation,
    extract_target,
    validate_target,
    run_scan,
    nmap_available,
    build_nmap_command,
)


# ============================================================
# CYBERLLM INTEGRATION
# ============================================================

def _get_cyberllm_response(message: str) -> str:
    """
    Send ordinary conversational messages to CyberLLM.

    API keys remain in the backend environment and are not
    returned to the frontend.
    """

    text = str(message or "").strip()

    if not text:
        return "Please say something!"

    try:
        from backend.cyberllm_client import generate_chat_response

        result = generate_chat_response(text)

        if not isinstance(result, dict):
            print("[Zyra/CyberLLM] Invalid response type.")
            return (
                "CyberLLM returned an unexpected response. "
                "Please try again."
            )

        answer = result.get("answer")

        if isinstance(answer, str) and answer.strip():
            return answer.strip()

        print("[Zyra/CyberLLM] Response did not contain an answer.")

        return (
            "CyberLLM did not return a usable answer. "
            "Please try again."
        )

    except Exception as exc:
        # Do not return exception details or credentials to the UI.
        print(
            "[Zyra/CyberLLM] Request failed: "
            f"{type(exc).__name__}: {exc}"
        )

        return (
            "I'm unable to get a response from CyberLLM right now. "
            "Please check that the CyberLLM API is running, "
            "then try again."
        )


# ============================================================
# GREETING AND IDENTITY
# ============================================================

def _normalize_greeting(message: str) -> str:
    """Normalize greeting text and surrounding punctuation."""

    return str(message or "").strip().lower().strip(
        " \t\r\n!.,?;:"
    )


def _zyra_greeting_answer(message: str) -> Optional[str]:
    """Return Zyra's exact greeting for known wake-phrase transcriptions."""

    normalized = _normalize_greeting(message)

    greetings = {
        # Standard greetings
        "hi zyra",
        "hello zyra",
        "hey zyra",

        # Observed speech-recognition variations
        "hay jara",
        "hey jara",
        "hi jara",
        "hello jara",
        "hey saira",
        "hi saira",
        "hello saira",
        "hey zara",
        "hi zara",
        "hello zara",
        "hey sairah",
        "hi sairah",
        "hey zyrah",
        "hi zyrah",
    }

    if normalized in greetings:
        return "Welcome, how can I help you"

    return None



def _zyra_identity_answer(message: str) -> Optional[str]:
    """Return Zyra's configured full form when requested."""

    text = str(message or "").strip().lower()

    if not text:
        return None

    if not any(alias in text for alias in ("zyra", "z y r a")):
        return None

    asks_meaning = any(
        term in text
        for term in (
            "full form",
            "full name",
            "stand for",
            "stands for",
            "abbreviation",
            "acronym",
            "meaning of",
            "what does",
            "expand",
        )
    )

    if asks_meaning:
        return (
            "ZYRA stands for Zero-latency Yielding "
            "Response Assistant."
        )

    return None


# ============================================================
# COMMAND MAP
# ============================================================

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


_voice_thread: Optional[threading.Thread] = None
_voice_running = False


# ============================================================
# NMAP RESPONSE
# ============================================================

def _nmap_starting_message(text: str) -> str:
    """Validate an Nmap target and describe the requested scan."""

    op_key, op = resolve_operation(text)

    target = extract_target(text) or op.get(
        "default_target",
        "127.0.0.1",
    )

    valid, msg = validate_target(target)

    if not valid:
        return (
            "NMAP SCANNER\n"
            f"Target: {target}\n"
            f"Operation: {op.get('label', op_key)}\n"
            f"Invalid target: {msg}. The scan was not started."
        )

    return (
        f"Running a {op['label']} scan on {target}. "
        "Check the Nmap Scanner panel for scan results."
    )


# ============================================================
# LINK CAPTURE AND ANALYSIS
# ============================================================

def _link_capture_report(message: str):
    """
    Analyze an explicitly supplied URL or attempt to capture
    the active URL.

    Returns:
        (report_text, url)
    """

    from backend.url_analyzer.intent import extract_target_urls

    candidates = extract_target_urls(message or "")

    if len(candidates) > 1:
        return (
            "I found multiple URLs. Please ask me to analyze "
            "one URL at a time.",
            None,
        )

    lowered = (message or "").lower()

    screen_request = any(
        phrase in lowered
        for phrase in (
            "on the screen",
            "on screen",
            "visible on screen",
            "current page",
            "this page",
            "page i'm on",
            "page i am on",
            "selected link",
            "selected url",
            "screen link",
            "link on my screen",
            "url on my screen",
            "website on the screen",
            "website on screen",
            "website on my screen",
            "page on screen",
            "page on the screen",
            "website on the current screen",
            "visible in my browser",
        )
    )

    # Prefer a URL supplied by the user unless they request
    # the currently visible browser URL.
    url = None if screen_request else extract_url(message)

    if not url:
        try:
            from screen_ocr import get_active_url

            url = get_active_url()

            if url:
                print(
                    "[Zyra/LinkAnalysis] Captured active browser URL."
                )

        except Exception as exc:
            print(
                "[Zyra/LinkAnalysis] URL capture unavailable: "
                f"{type(exc).__name__}"
            )

    if not url:
        return None, None

    result = analyze_url_security(url)

    return format_security_report(result), url


# ============================================================
# MAIN CHAT ROUTER
# ============================================================

def process_chat(message: str) -> str:
    """
    Route a text message through Zyra's existing capabilities.

    Routing order:
        1. Validate input.
        2. Greeting.
        3. Zyra identity.
        4. Link security.
        5. System monitoring.
        6. DNS.
        7. Nmap.
        8. CyberLLM.
    """

    if not message or not str(message).strip():
        return "Please say something!"

    message = str(message).strip()

    greeting = _zyra_greeting_answer(message)

    if greeting:
        return greeting

    identity = _zyra_identity_answer(message)

    if identity:
        return identity

    if is_link_analysis_request(message):
        report, _url = _link_capture_report(message)

        if report is not None:
            return report

        return (
            "I couldn't find a link to analyze. Please provide a URL "
            "or make the page visible in your browser."
        )

    if is_system_monitor_intent(message):
        return answer_system_query(message)

    if is_dns_intent(message):
        target = extract_dns_target(message)
        return dns_build_chat_ack(target)

    if is_nmap_intent(message):
        return _nmap_starting_message(message)

    return _get_cyberllm_response(message)


# ============================================================
# STREAMING CHAT ROUTER
# ============================================================

def process_chat_stream(message: str) -> Dict[str, Any]:
    """
    Preserve the existing WebSocket response contract.

    Normal CyberLLM responses are returned as a completed static
    response here, not token-by-token streaming.
    """

    if not message or not str(message).strip():
        return {
            "kind": "static",
            "success": True,
            "data": "Please say something!",
        }

    text = str(message).strip()

    greeting = _zyra_greeting_answer(text)

    if greeting:
        return {
            "kind": "static",
            "success": True,
            "data": greeting,
        }

    identity = _zyra_identity_answer(text)

    if identity:
        return {
            "kind": "static",
            "success": True,
            "data": identity,
        }

    if is_link_analysis_request(text):
        if extract_url(text):
            report, _url = _link_capture_report(text)

            return {
                "kind": "static",
                "success": True,
                "data": report or "I couldn't analyze that URL.",
            }

        return {
            "kind": "capture",
            "success": True,
            "question": text,
        }

    if is_system_monitor_intent(text):
        return {
            "kind": "static",
            "success": True,
            "data": answer_system_query(text),
            "monitor_topic": classify_system_query(text) or "overall",
        }

    if is_dns_intent(text):
        return {
            "kind": "static",
            "success": True,
            "data": dns_build_chat_ack(extract_dns_target(text)),
            "action": "dns_lookup",
            "dns_request": text,
        }

    if is_nmap_intent(text):
        return {
            "kind": "static",
            "success": True,
            "data": _nmap_starting_message(text),
            "action": "nmap_scan",
            "nmap_request": text,
        }

    return {
        "kind": "static",
        "success": True,
        "data": _get_cyberllm_response(text),
        "provider": "cyberllm",
    }


# ============================================================
# PROGRAMMATIC COMMAND EXECUTION
# ============================================================

def process_command(
    command_name: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a named Zyra command."""

    if not command_name:
        return {
            "success": False,
            "error": "No command specified",
        }

    command_name = command_name.lower().strip()
    params = params or {}

    if command_name.startswith("close_"):
        app_name = command_name.replace("close_", "", 1).strip()

        try:
            response = close_app(app_name)

            return {
                "success": True,
                "data": response,
            }

        except Exception as exc:
            print(
                "[Zyra/Command] Close failed: "
                f"{type(exc).__name__}"
            )

            return {
                "success": False,
                "error": f"Could not close {app_name}",
            }

    if command_name.startswith("search_google"):
        query = params.get("query", "")

        if not query:
            return {
                "success": False,
                "error": "No search query provided",
            }

        search_google(query)

        return {
            "success": True,
            "data": f"Searched Google for {query}",
        }

    if command_name.startswith("search_youtube"):
        query = params.get("query", "")

        if not query:
            return {
                "success": False,
                "error": "No search query provided",
            }

        search_youtube(query)

        return {
            "success": True,
            "data": f"Searched YouTube for {query}",
        }

    if command_name in COMMAND_MAP:
        try:
            COMMAND_MAP[command_name]()

            return {
                "success": True,
                "data": f"Executed {command_name}",
            }

        except Exception as exc:
            print(
                "[Zyra/Command] Command failed: "
                f"{type(exc).__name__}"
            )

            return {
                "success": False,
                "error": f"Could not execute {command_name}",
            }

    return {
        "success": False,
        "error": f"Unknown command: {command_name}",
    }


# ============================================================
# VOICE COMMAND PROCESSING
# ============================================================

def process_voice_command(
    transcribed_text: str,
) -> Dict[str, Any]:
    """Process speech transcription, commands and normal chat."""

    if not transcribed_text or not str(transcribed_text).strip():
        return {
            "response": "",
            "action": "none",
        }

    text = str(transcribed_text).strip()
    lowered = text.lower()

    greeting = _zyra_greeting_answer(text)

    if greeting:
        return {
            "response": greeting,
            "action": "greeting",
        }

    identity = _zyra_identity_answer(text)

    if identity:
        return {
            "response": identity,
            "action": "identity",
        }

    # Close an application.
    if lowered.startswith("close "):
        app = lowered.replace("close ", "", 1).strip()

        try:
            response = close_app(app)

            return {
                "response": response,
                "action": "close_app",
            }

        except Exception:
            return {
                "response": f"Could not close {app}.",
                "action": "error",
            }

    # Save a preference.
    marker = "my favorite language is"

    if marker in lowered:
        language = text[lowered.index(marker) + len(marker):].strip()

        if language:
            remember("favorite_language", language)

            return {
                "response": (
                    f"I'll remember that. Your favorite language "
                    f"is {language}."
                ),
                "action": "remember",
            }

    # Retrieve a preference.
    if "what is my favorite language" in lowered:
        language = recall("favorite_language")

        if language:
            response = f"Your favorite language is {language}."
        else:
            response = "I don't know your favorite language yet."

        return {
            "response": response,
            "action": "recall",
        }

    # Exit requests.
    if any(
        phrase in lowered
        for phrase in (
            "exit",
            "quit",
            "goodbye",
            "shut it down",
        )
    ):
        return {
            "response": "Goodbye. Have a nice day.",
            "action": "exit",
        }

    # Link security.
    if is_link_analysis_request(text):
        report, _url = _link_capture_report(text)

        if report is None:
            report = (
                "I couldn't find a link to analyze. "
                "Please provide a URL or show it in your browser."
            )

        return {
            "response": report,
            "action": "link_analysis",
        }

    # System monitoring.
    if is_system_monitor_intent(text):
        metrics = get_system_metrics()
        topic = classify_system_query(text) or "overall"

        if topic != "overall":
            return {
                "response": answer_system_query(text, metrics),
                "action": "system_monitor_answer",
                "topic": topic,
            }

        return {
            "response": get_voice_summary(metrics),
            "action": "system_monitor",
            "metrics": metrics,
            "formatted": format_system_monitor_text(metrics),
        }

    # DNS lookup.
    if is_dns_intent(text):
        target = extract_dns_target(text)

        return {
            "response": dns_build_chat_ack(target),
            "action": "dns_lookup",
            "dns_request": text,
        }

    # Nmap.
    if is_nmap_intent(text):
        return {
            "response": _nmap_starting_message(text),
            "action": "nmap_scan",
            "nmap_request": text,
        }

    # Natural-language command mappings.
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
        if phrase not in lowered:
            continue

        try:
            COMMAND_MAP[command]()

            responses = {
                "open_chrome": "Opening Chrome.",
                "open_vscode": "Opening Visual Studio Code.",
                "open_notepad": "Opening Notepad.",
                "open_calculator": "Opening Calculator.",
                "open_cmd": "Opening Command Prompt.",
                "open_powershell": "Opening PowerShell.",
                "open_task_manager": "Opening Task Manager.",
                "open_control_panel": "Opening Control Panel.",
                "open_file_explorer": "Opening File Explorer.",
                "open_settings": "Opening Settings.",
                "open_google": "Opening Google.",
                "open_youtube": "Opening YouTube.",
                "open_github": "Opening GitHub.",
                "open_chatgpt": "Opening ChatGPT.",
                "open_gmail": "Opening Gmail.",
                "open_leetcode": "Opening LeetCode.",
                "open_linkedin": "Opening LinkedIn.",
                "open_downloads": "Opening Downloads.",
                "open_documents": "Opening Documents.",
                "open_desktop": "Opening Desktop.",
                "open_camera": "Opening Camera.",
                "shutdown": "Shutting down the PC.",
                "restart": "Restarting the PC.",
                "sleep": "Putting the PC to sleep.",
                "lock_pc": "Locking the PC.",
                "screenshot": "Taking a screenshot.",
                "volume_up": "Increasing volume.",
                "volume_down": "Decreasing volume.",
                "mute": "Muting volume.",
                "wifi_on": "Turning on Wi-Fi.",
                "wifi_off": "Turning off Wi-Fi.",
                "empty_recycle_bin": "Emptying the Recycle Bin.",
                "current_time": "Fetching current time.",
                "current_date": "Fetching current date.",
                "play_music": "Playing music.",
            }

            return {
                "response": responses.get(
                    command,
                    f"Executed {command}.",
                ),
                "action": command,
            }

        except Exception as exc:
            print(
                "[Zyra/VoiceCommand] Command failed: "
                f"{type(exc).__name__}"
            )

            return {
                "response": f"Could not execute {command}.",
                "action": "error",
            }

    # Google search.
    if "search google for" in lowered:
        query = text[lowered.index("search google for") + len("search google for"):].strip()

        if query:
            search_google(query)

            return {
                "response": f"Searching Google for {query}.",
                "action": "search_google",
            }

    # YouTube search.
    if "search youtube for" in lowered:
        query = text[lowered.index("search youtube for") + len("search youtube for"):].strip()

        if query:
            search_youtube(query)

            return {
                "response": f"Searching YouTube for {query}.",
                "action": "search_youtube",
            }

    # Default: CyberLLM conversational answer.
    return {
        "response": _get_cyberllm_response(text),
        "action": "chat",
        "provider": "cyberllm",
    }


# ============================================================
# TEXT-TO-SPEECH
# ============================================================

def speak_text(text: str) -> None:
    """Speak text in a background thread when speech is available."""

    if not text:
        return

    if not _SPEECH_AVAILABLE:
        print("[Zyra/Speech] Skipping speech: dependencies unavailable.")
        return

    thread = threading.Thread(
        target=speak,
        args=(text,),
        daemon=True,
    )

    thread.start()


# ============================================================
# UNIFIED MESSAGE PROCESSOR
# ============================================================

def process_message(
    message_type: str,
    data: Any,
) -> Dict[str, Any]:
    """Unified message processor compatible with bridge_server.py."""

    # Chat.
    if message_type == "chat":
        if isinstance(data, str):
            return {
                "success": True,
                "data": process_chat(data),
            }

        return {
            "success": False,
            "error": "Invalid chat data",
        }

    # Commands.
    if message_type == "command":
        if isinstance(data, str):
            return process_command(data)

        if isinstance(data, dict):
            return process_command(
                data.get("command", ""),
                data,
            )

        return {
            "success": False,
            "error": "Invalid command data",
        }

    # Voice transcription.
    if message_type == "voice":
        if isinstance(data, str):
            return {
                "success": True,
                "data": process_voice_command(data),
            }

        return {
            "success": False,
            "error": "Invalid voice data",
        }

    # Remember.
    if message_type == "remember":
        if isinstance(data, dict):
            key = data.get("key")
            value = data.get("value")

            if not key:
                return {
                    "success": False,
                    "error": "A memory key is required",
                }

            remember(key, value)

            return {
                "success": True,
                "data": f"Remembered {key}",
            }

        return {
            "success": False,
            "error": "Invalid remember data",
        }

    # Recall.
    if message_type == "recall":
        if isinstance(data, str):
            return {
                "success": True,
                "data": recall(data),
            }

        return {
            "success": False,
            "error": "Invalid recall data",
        }

    # Speak.
    if message_type == "speak":
        if isinstance(data, str):
            speak_text(data)

            return {
                "success": _SPEECH_AVAILABLE,
                "data": (
                    "Speaking"
                    if _SPEECH_AVAILABLE
                    else "Speech dependencies are unavailable."
                ),
            }

        return {
            "success": False,
            "error": "Invalid speak data",
        }

    # Link analysis.
    if message_type == "analyze_link":
        if isinstance(data, str):
            text = data

        elif isinstance(data, dict):
            text = data.get("url") or data.get("text") or ""

        else:
            return {
                "success": False,
                "error": "Invalid analyze_link data",
            }

        url = extract_url(text) if text else None

        if not url:
            return {
                "success": False,
                "error": "No URL found to analyze",
            }

        try:
            result = analyze_url_security(url)

            return {
                "success": True,
                "data": {
                    "report": format_security_report(result),
                    "analysis": result,
                },
            }

        except Exception as exc:
            print(
                "[Zyra/LinkAnalysis] Analysis failed: "
                f"{type(exc).__name__}"
            )

            return {
                "success": False,
                "error": "Could not analyze the supplied URL",
            }

    # System metrics.
    if message_type in (
        "system_metrics",
        "get_system_metrics",
        "monitor_system",
        "start_monitoring",
    ):
        metrics = get_system_metrics()

        return {
            "success": True,
            "data": metrics,
            "formatted": format_system_monitor_text(metrics),
            "summary": get_voice_summary(metrics),
        }

    # Nmap status.
    if message_type == "nmap_status":
        status = nmap_available()

        return {
            "success": True,
            "data": {
                "available": status.get("available", False),
                "version": status.get("version", "unknown"),
                "error": status.get("error"),
            },
        }

    return {
        "success": False,
        "error": f"Unknown type: {message_type}",
    }
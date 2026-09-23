import threading
import time
import os
import sys
import signal
import webbrowser
import subprocess
import platform
import urllib.request
import urllib.error

# ── Windows console safety ──────────────────────────────────────────────
# Force UTF-8 output before any module that prints emoji is imported, so
# status prints never crash with UnicodeEncodeError on cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from listen import listen, warm_up_async as warm_up_speech_async
from speak import (
    speak,
    speak_async,
    stop_speaking,
    is_speaking,
    wait_until_done,
    warm_up_async as warm_up_voice_async,
)
from brain import (
    ask_ai,
    ask_ai_stream,
    begin_request_session,
    cancel_current_request,
    is_current_session,
)
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
from memory import remember, recall
from backend.server import start_server_thread, broadcast_system_monitor_trigger
from zyra_handler import handle_analyze_link_intent, is_link_analysis_intent
from backend.url_analyzer import (
    extract_target_url,
    is_url_analysis_intent,
)
from backend.dns_lookup import (
    extract_dns_target,
    is_dns_intent,
)
from system_monitor import (
    is_system_monitor_intent,
    format_system_monitor_text,
    get_voice_summary,
    get_system_metrics,
)
from nmap_handler import handle_nmap_intent, is_nmap_intent

# ========== Configuration ==========
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
DASHBOARD_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

# Global state for clean shutdown
server_thread = None
edge_process = None
desktop_shell_process = None
running = True


def find_edge_path():
    """
    Find Microsoft Edge executable path on Windows.
    Checks common installation paths and falls back to 'where' command.
    """
    possible_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # Try to find via where command
    try:
        result = subprocess.run(
            ["where", "msedge"],
            capture_output=True,
            text=True,
            shell=True,
        )

        if result.returncode == 0:
            edge_path = result.stdout.strip().split("\n")[0].strip()

            if edge_path:
                return edge_path
    except Exception:
        pass

    return None


def register_edge_browser():
    """
    Register Microsoft Edge as the preferred browser in the webbrowser module.
    This ensures webbrowser.open() uses Edge explicitly when called.
    """
    edge_path = find_edge_path()

    if edge_path:
        webbrowser.register(
            "edge",
            None,
            webbrowser.BackgroundBrowser(edge_path),
            preferred=True,
        )

        print(f"   ✅ Microsoft Edge registered: {edge_path}")
        return True
    else:
        print("   ⚠️  Microsoft Edge not found — will use default browser")
        return False


def find_electron_path():
    """
    Find the Electron executable shipped with the ZYRA desktop shell.
    Looks in the project's node_modules first, then the ZYRA_ELECTRON
    environment variable, then a system-wide electron on PATH.
    """
    project_root = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(
            project_root,
            "node_modules",
            "electron",
            "dist",
            "electron.exe",
        ),
        os.path.join(
            project_root,
            "node_modules",
            "electron",
            "dist",
            "electron",
        ),
        os.path.expanduser(r"~\.zyra\bin\electron.exe"),
    ]

    env_override = os.environ.get("ZYRA_ELECTRON")

    if env_override:
        candidates.insert(0, env_override)

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return None


def open_dashboard_in_electron(url):
    """
    Open the ZYRA dashboard in the native desktop window (Electron shell).

    Args:
        url: The dashboard URL to open (e.g. http://127.0.0.1:8080)

    Returns:
        bool: True if the desktop window was launched, False if Electron
              is unavailable (caller should fall back to the browser).
    """
    global electron_process

    electron_path = find_electron_path()

    if not electron_path:
        print("   ⚠️  ZYRA desktop shell not found — falling back to browser")
        return False

    print("\n🖥️  Opening ZYRA Dashboard in desktop window...")
    print(f"   URL: {url}")

    try:
        project_root = os.path.dirname(os.path.abspath(__file__))

        electron_process = subprocess.Popen(
            [electron_path, project_root],
            cwd=project_root,
            env={**os.environ, "ZYRA_URL": url},
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print("   ✅ Dashboard opened in ZYRA desktop window")
        return True

    except Exception as e:
        print(
            f"   ⚠️  Desktop window failed ({e}) — falling back to browser..."
        )

        electron_process = None
        return False


def open_dashboard_in_edge(url):
    """
    Open the ZYRA dashboard in the desktop window (preferred) or Microsoft Edge.
    Uses subprocess for direct control, with webbrowser fallback.

    Args:
        url: The dashboard URL to open (e.g. http://127.0.0.1:8080)
    """
    global edge_process

    # Preferred: native desktop window (ZYRA Desktop shell)
    if open_dashboard_in_electron(url):
        return True

    print(f"\n🌐 Opening ZYRA Dashboard in Microsoft Edge...")
    print(f"   URL: {url}")

    edge_path = find_edge_path()

    if edge_path:
        try:
            edge_process = subprocess.Popen(
                [
                    edge_path,
                    "--new-window",
                    "--kiosk",
                    "--no-first-run",
                    "--disable-features=msUndersideButton,msSidebar",
                    url,
                ],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            print(
                "   ✅ Dashboard opened in Microsoft Edge (fullscreen/kiosk mode)"
            )

            return True

        except Exception as e:
            print(
                f"   ⚠️  Edge subprocess failed ({e}), trying webbrowser fallback..."
            )

    # Fallback: use webbrowser module with Edge registration
    try:
        webbrowser.get("edge").open(url, new=2)
    except Exception:
        webbrowser.open(url, new=2)

    print("   ✅ Dashboard opened in browser")
    return True


def find_desktop_shell_command():
    """
    Locate the ZYRA Desktop shell (Electron) bundled with the project.

    Returns:
        tuple: (electron_exe_path, shell_dir) or (None, None) when unavailable
    """
    project_root = os.path.dirname(os.path.abspath(__file__))

    electron_exe = os.path.join(
        project_root,
        "node_modules",
        "electron",
        "dist",
        "electron.exe",
    )

    shell_dir = os.path.join(project_root, "desktop")
    shell_manifest = os.path.join(shell_dir, "package.json")

    if os.path.exists(electron_exe) and os.path.exists(shell_manifest):
        return electron_exe, shell_dir

    return None, None


def open_dashboard_in_desktop_shell(url):
    """
    Launch the dashboard in the native ZYRA Desktop window (Electron shell).

    The backend server is already running inside THIS Python process, so the
    shell is launched in "external" mode (ZYRA_EXTERNAL_SHELL=1): it only
    opens the native window pointing at the existing server — it does not
    spawn its own backend. When the window is closed, the shell stops this
    Python process (ZYRA_PARENT_PID), so the whole app shuts down cleanly.

    Returns:
        bool: True when the desktop window was launched, False when the
              shell is unavailable (caller can fall back to the browser).
    """
    global desktop_shell_process

    electron_exe, shell_dir = find_desktop_shell_command()

    if not electron_exe:
        print(
            "   ⚠️  ZYRA Desktop shell not found (node_modules/electron missing)"
        )
        return False

    try:
        env = os.environ.copy()

        env["ZYRA_EXTERNAL_SHELL"] = "1"
        env["ZYRA_URL"] = url
        env["ZYRA_PARENT_PID"] = str(os.getpid())

        desktop_shell_process = subprocess.Popen(
            [electron_exe, shell_dir],
            cwd=os.path.dirname(shell_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print("   ✅ ZYRA Desktop window launched")
        return True

    except Exception as e:
        print(
            f"   ⚠️  Could not launch the ZYRA Desktop shell ({e})"
        )

        desktop_shell_process = None
        return False


def wait_for_server(url, max_retries=10, retry_interval=1.0):
    """
    Poll the backend server's health endpoint until it responds.
    This ensures the server is fully initialized before opening the browser.

    Args:
        url: Base URL of the server (e.g. http://127.0.0.1:8080)
        max_retries: Maximum number of retry attempts
        retry_interval: Seconds to wait between retries

    Returns:
        bool: True if server is ready, False if all retries exhausted
    """
    health_url = f"{url}/api/health"

    print(f"\n⏳ Waiting for backend server to be ready...")

    for attempt in range(1, max_retries + 1):
        try:
            response = urllib.request.urlopen(
                health_url,
                timeout=2,
            )

            if response.status == 200:
                print(
                    f"   ✅ Backend server is ready (attempt {attempt})"
                )
                return True

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            ConnectionRefusedError,
            TimeoutError,
            OSError,
        ):
            pass

        if attempt < max_retries:
            print(
                f"   ⏳ Waiting... (attempt {attempt}/{max_retries})"
            )
            time.sleep(retry_interval)

    print(
        f"   ⚠️  Server not ready after {max_retries} attempts — proceeding anyway"
    )

    return False


def signal_handler(signum, frame):
    """
    Handle OS signals (SIGINT from Ctrl+C, SIGTERM) for graceful shutdown.
    Sets the global 'running' flag to False so the main loop exits cleanly.
    """
    global running

    print("\n\n🛑 Shutdown signal received. Cleaning up...")

    running = False


def cleanup():
    """
    Perform clean shutdown of all spawned processes:
    - Terminate the ZYRA Desktop window if we launched it
    - Terminate the Edge browser process if we launched it
    - The backend server thread is a daemon and will exit automatically
    """
    global electron_process
    global edge_process
    global desktop_shell_process

    print("\n🧹 Cleaning up...")

    # Stop the voice pipeline first: end the listening session and cut off any
    # speech still queued or playing.
    try:
        import listen as _listen

        _listen.stop_listening()

    except Exception:
        pass

    try:
        stop_speaking(clear_queue=True)

    except Exception:
        pass

    if desktop_shell_process is not None:
        try:
            desktop_shell_process.terminate()
            desktop_shell_process.wait(timeout=3)

            print("   ✅ ZYRA Desktop window closed")

        except Exception:
            try:
                desktop_shell_process.kill()

                print("   ✅ ZYRA Desktop window force-closed")

            except Exception:
                pass

        desktop_shell_process = None

    if electron_process is not None:
        try:
            electron_process.terminate()
            electron_process.wait(timeout=3)

            print("   ✅ Desktop window closed")

        except Exception:
            try:
                electron_process.kill()

                print("   ✅ Desktop window force-closed")

            except Exception:
                pass

        electron_process = None

    if edge_process is not None:
        try:
            edge_process.terminate()
            edge_process.wait(timeout=3)

            print("   ✅ Edge browser closed")

        except Exception:
            try:
                edge_process.kill()

                print("   ✅ Edge browser force-closed")

            except Exception:
                pass

        edge_process = None

    print("   ✅ Cleanup complete")


def start_backend_server():
    """
    Start the FastAPI backend server in a background daemon thread.
    The server serves the dashboard UI and WebSocket/API endpoints.

    Returns:
        threading.Thread: The daemon thread running the server
    """
    global server_thread

    print("\n" + "=" * 50)
    print("🚀 Starting ZYRA Backend Server...")
    print("=" * 50)

    # Start server WITHOUT opening browser - we control browser launch here
    server_thread = start_server_thread(
        host=SERVER_HOST,
        port=SERVER_PORT,
        open_browser=False,
    )

    print(f"\n✅ Dashboard will be available at: {DASHBOARD_URL}")
    print("📡 WebSocket: ws://127.0.0.1:8080/ws")
    print("📋 API Docs: http://127.0.0.1:8080/docs")
    print("=" * 50 + "\n")

    return server_thread


# ========== URL Analyzer Voice Integration ==========
# Real backend URL scans are streamed to the dashboard panel by the server
# (start_url_scan broadcasts live status over WebSocket). This voice entry
# point reuses the existing listen() speech-to-text loop: it detects the
# URL_ANALYSIS intent, opens the panel, and speaks the result when the scan
# completes.


def _broadcast_url_analyzer(url: str, state=None):
    """Open the URL Analyzer panel on every connected dashboard client."""
    try:
        from backend.server import broadcast_message_sync

        broadcast_message_sync(
            {
                "type": "show_url_analyzer",
                "data": state,
                "url": url,
            }
        )

    except Exception:
        pass


def _url_voice_completion_watcher(scan_id: str):
    """
    Poll the in-memory scan registry until the analysis finishes, then speak
    the voice summary (or a failure notice). Best-effort background thread.
    """
    try:
        from backend.url_analyzer import build_voice_summary
        from backend.url_analyzer.analyzer import get_scan_state

    except Exception as e:
        print(f"[URL WATCHER] import error: {e}")
        return

    deadline = time.time() + 100

    while time.time() < deadline:
        try:
            state = get_scan_state(scan_id)

        except Exception:
            state = None

        if state:
            status = str(state.get("status") or "").upper()

            if status == "COMPLETE":
                result = state.get("result")

                if result:
                    try:
                        speak(build_voice_summary(result))
                    except Exception:
                        pass

                return

            if status == "ERROR":
                reason = state.get("error") or "Please try again."

                speak(
                    f"The URL analysis failed. {reason}"
                )

                return

        time.sleep(1.0)

    speak(
        "The URL analysis could not be completed within the allowed time."
    )


def handle_url_analysis_voice(command: str):
    """
    Voice entry point for the ZYRA URL Analyzer.

    When a URL is present in the spoken command it is analyzed for real by the
    backend: the scan runs in a background thread, live progress streams to
    the dashboard's URL Analyzer panel, and the spoken summary is delivered on
    completion. When no URL was spoken it falls back to the existing
    screen/clipboard link-analysis handler so legacy behavior is preserved.
    """
    from backend.server import start_url_scan

    target = extract_target_url(command)

    if not target:
        print(
            "   🔗 No URL in the command — falling back to screen/clipboard link analysis."
        )

        result = handle_analyze_link_intent(command)

        if result and result.get("success") and result.get("checks"):
            print(
                f"   🔗 URL: {result.get('url')} | "
                f"Score: {result.get('score')} | "
                f"Verdict: {result.get('verdict')}"
            )

        return

    print(f"\n🔗 Starting ZYRA URL Analyzer on: {target}")

    launch = start_url_scan(
        target,
        source="voice",
    )

    if not launch.get("success"):
        reason = launch.get("error") or "Please try again."

        print(
            f"   ⚠️  URL scan could not start: {reason}"
        )

        speak(
            f"I couldn't start the URL analysis. {reason}"
        )

        return

    _broadcast_url_analyzer(target)

    print(
        "   📡 URL Analyzer panel open — streaming live progress to the dashboard."
    )

    speak(
        f"Running a security analysis on {target}. Please wait."
    )

    threading.Thread(
        target=_url_voice_completion_watcher,
        args=(launch["scan_id"],),
        daemon=True,
    ).start()


# ========== DNS Lookup Voice Integration ==========
# Real backend DNS lookups are streamed to the dashboard panel by the server
# (start_dns_lookup_job broadcasts live status over WebSocket). This voice
# entry point reuses the existing listen() speech-to-text loop: it detects
# the DNS_LOOKUP intent, opens the panel, and speaks the result when the
# lookup completes.


def _broadcast_dns_lookup(domain: str, state=None):
    """Open the DNS Lookup panel on every connected dashboard client."""
    try:
        from backend.server import broadcast_message_sync

        broadcast_message_sync(
            {
                "type": "show_dns_lookup",
                "data": state,
                "domain": domain,
            }
        )

    except Exception:
        pass


def _dns_voice_completion_watcher(lookup_id: str):
    """
    Poll the in-memory lookup registry until the lookup finishes, then speak
    the voice summary (or a failure notice). Best-effort background thread.
    """
    try:
        from backend.dns_lookup import (
            build_voice_summary as build_dns_voice_summary
        )

        from backend.dns_lookup.analyzer import get_scan_state

    except Exception as e:
        print(f"[DNS WATCHER] import error: {e}")
        return

    deadline = time.time() + 100

    while time.time() < deadline:
        try:
            state = get_scan_state(lookup_id)

        except Exception:
            state = None

        if state:
            status = str(state.get("status") or "").upper()

            if status == "COMPLETE":
                result = state.get("result")

                if result:
                    try:
                        speak(
                            build_dns_voice_summary(result)
                        )
                    except Exception:
                        pass

                return

            if status == "ERROR":
                reason = state.get("error") or "Please try again."

                speak(
                    f"The DNS lookup failed. {reason}"
                )

                return

        time.sleep(1.0)

    speak(
        "The DNS lookup could not be completed within the allowed time."
    )


def handle_dns_analysis_voice(command: str):
    """
    Voice entry point for the ZYRA DNS Lookup.

    When a domain (or IP) is present in the spoken command a real DNS lookup
    runs in the backend: progress streams to the dashboard's DNS Lookup
    panel and the spoken summary is delivered on completion. When no domain
    was spoken, ZYRA asks for one.
    """
    from backend.server import start_dns_lookup_job

    target = extract_dns_target(command)

    if not target:
        print(
            "   🌐 No domain in the command — asking the user for one."
        )

        speak(
            "DNS Lookup activated. Please tell me the domain you want me to look up, for example, analyze DNS of example dot com."
        )

        return

    print(f"\n🌐 Starting ZYRA DNS Lookup on: {target}")

    launch = start_dns_lookup_job(
        target,
        source="voice",
    )

    if not launch.get("success"):
        reason = launch.get("error") or "Please try again."

        print(
            f"   ⚠️  DNS lookup could not start: {reason}"
        )

        speak(
            f"I couldn't start the DNS lookup. {reason}"
        )

        return

    _broadcast_dns_lookup(target)

    print(
        "   📡 DNS Lookup panel open — streaming live progress to the dashboard."
    )

    speak(
        f"Looking up DNS records for {target}. Please wait."
    )

    threading.Thread(
        target=_dns_voice_completion_watcher,
        args=(launch["lookup_id"],),
        daemon=True,
    ).start()


# ========== Voice turn state (exactly one pipeline per utterance) ==========
# Every utterance opens ONE turn. Starting a turn cancels any in-flight AI
# generation and clears the TTS queue, so a stale answer can never be spoken
# after a newer request has arrived. Barge-in (the user speaking while ZYRA is
# talking) uses the same path: interrupt → clear → capture → process.

_turn_lock = threading.Lock()
_turn_counter = 0


def start_voice_turn() -> int:
    """Open a new voice turn, cancelling the previous answer completely."""
    global _turn_counter

    with _turn_lock:
        _turn_counter += 1
        turn = _turn_counter

    cancel_current_request()
    stop_speaking(clear_queue=True)

    return turn


def _turn_is_current(turn: int) -> bool:
    with _turn_lock:
        return turn == _turn_counter


def answer_voice_stream(command: str, turn: int) -> None:
    """Stream the AI answer: first sentence → TTS while the rest generates.

    Runs in its own thread so the main loop can immediately go back to
    listening (which is what makes barge-in possible). Only the newest turn may
    speak: any older turn stops silently.
    """
    session_id = begin_request_session()

    print("🧠 ZYRA thinking...")

    try:
        for sentence in ask_ai_stream(
            command,
            session_id=session_id,
        ):
            if (
                not _turn_is_current(turn)
                or not is_current_session(session_id)
            ):
                print(
                    "⏹️  Reply cancelled — a newer request took over."
                )

                return

            speak_async(sentence)

        # Let the queued sentences finish; barge-in can interrupt this wait.
        wait_until_done(timeout=300)

    except Exception as exc:
        print(
            f"⚠️  Voice answer failed: {type(exc).__name__}: {exc}"
        )


# ========== Main Entry Point ==========

if __name__ == "__main__":
    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("""
    ╔══════════════════════════════════════╗
    ║          ZYRA AI ASSISTANT           ║
    ║     Voice + Dashboard + API          ║
    ╚══════════════════════════════════════╝
    """)

    # Register Microsoft Edge as the preferred browser
    register_edge_browser()

    # Start the backend server in background thread (non-blocking)
    server_thread = start_backend_server()

    # Wait for the server to be fully initialized and listening
    # This polls the /api/health endpoint with retries
    server_ready = wait_for_server(
        DASHBOARD_URL,
        max_retries=8,
        retry_interval=1.0,
    )

    # ZYRA Desktop mode: the Electron desktop shell (desktop/main.js) loads
    # the dashboard in its own native window, so the Edge-kiosk browser
    # launch must be skipped. Normal `python main.py` behavior is unchanged.
    if os.environ.get("ZYRA_DESKTOP") == "1":
        if server_ready:
            print(
                "\n🖥️  ZYRA Desktop mode — dashboard is served to the ZYRA desktop window"
            )
        else:
            print(
                "\n⚠️  Server may not be fully ready. The desktop window will retry."
            )

        print("\n✨ ZYRA is now running!")
        print("   🎤 Voice commands: Speak into your microphone")
        print(
            "   🖥️  Dashboard: ZYRA desktop window (http://127.0.0.1:8080)"
        )
        print("   ⌨️  Say 'exit' or press Ctrl+C to quit\n")

    else:
        # Default: open the dashboard in the native ZYRA Desktop window
        shell_started = open_dashboard_in_desktop_shell(
            DASHBOARD_URL
        )

        if not shell_started:
            # Desktop shell unavailable (node_modules/electron missing) —
            # fall back to the classic Microsoft Edge kiosk mode.
            print(
                "   ↪️  Falling back to Microsoft Edge kiosk mode"
            )

            if server_ready:
                open_dashboard_in_edge(DASHBOARD_URL)

            else:
                print(
                    "\n⚠️  Server may not be fully ready. Attempting to open dashboard anyway..."
                )

                open_dashboard_in_edge(DASHBOARD_URL)

        print("\n✨ ZYRA is now running!")
        print("   🎤 Voice commands: Speak into your microphone")
        print(
            "   🖥️  Dashboard: ZYRA Desktop window (http://127.0.0.1:8080)"
        )
        print("   ⌨️  Say 'exit' or press Ctrl+C to quit\n")

    # Warm up the voice stack in the background so the first utterance is fast:
    # the STT model loads, the TTS voice session is established and (via the
    # backend) the Ollama model is pulled into memory.
    warm_up_speech_async()
    warm_up_voice_async()

    speak(
        "Hello, I am Zyra. How can I help you today?"
    )

    try:
        while running:
            try:
                # While ZYRA is speaking the microphone stays open in barge-in
                # mode: if the user starts talking, the current answer is cut
                # off, its queue is cleared and the new request is processed.
                # is_speaking is passed as a callable so it is evaluated per
                # audio frame (playback may start mid-capture).
                command = listen(
                    should_continue=lambda: running,
                    barge_in=is_speaking,
                )

                if not command:
                    continue

                # Preserve the recognized text for the AI (natural casing and
                # punctuation improve answer quality) and match intents on a
                # lowercase copy of it.
                spoken_text = command
                command = command.lower()

                # ONE pipeline per utterance: this cancels any answer still in
                # flight and clears anything still queued for speech.
                turn = start_voice_turn()

                if command.startswith("close "):
                    app = command.replace(
                        "close ",
                        "",
                    ).strip()

                    response = close_app(app)

                    print(response)
                    speak(response)

                elif "open chrome" in command:
                    speak("Opening Chrome")
                    open_chrome()

                elif (
                    "open vscode" in command
                    or "open visual studio code" in command
                ):
                    speak("Opening Visual Studio Code")
                    open_vscode()

                elif "open notepad" in command:
                    speak("Opening Notepad")
                    open_notepad()

                elif "open calculator" in command:
                    speak("Opening Calculator")
                    open_calculator()

                elif (
                    "open cmd" in command
                    or "open command prompt" in command
                ):
                    speak("Opening Command Prompt")
                    open_cmd()

                elif "open powershell" in command:
                    speak("Opening PowerShell")
                    open_powershell()

                elif "open task manager" in command:
                    speak("Opening Task Manager")
                    open_task_manager()

                elif "open control panel" in command:
                    speak("Opening Control Panel")
                    open_control_panel()

                elif (
                    "open file explorer" in command
                    or "open explorer" in command
                ):
                    speak("Opening File Explorer")
                    open_file_explorer()

                elif "open settings" in command:
                    speak("Opening Settings")
                    open_settings()

                elif "open google" in command:
                    speak("Opening Google")
                    open_google()

                elif "open youtube" in command:
                    speak("Opening YouTube")
                    open_youtube()

                elif "open github" in command:
                    speak("Opening GitHub")
                    open_github()

                elif "open chatgpt" in command:
                    speak("Opening ChatGPT")
                    open_chatgpt()

                elif "open gmail" in command:
                    speak("Opening Gmail")
                    open_gmail()

                elif "open leetcode" in command:
                    speak("Opening LeetCode")
                    open_leetcode()

                elif "open linkedin" in command:
                    speak("Opening LinkedIn")
                    open_linkedin()

                elif "search google for" in command:
                    query = command.replace(
                        "search google for",
                        "",
                    ).strip()

                    speak(f"Searching Google for {query}")
                    search_google(query)

                elif "search youtube for" in command:
                    query = command.replace(
                        "search youtube for",
                        "",
                    ).strip()

                    speak(f"Searching YouTube for {query}")
                    search_youtube(query)

                elif "open downloads" in command:
                    speak("Opening Downloads")
                    open_downloads()

                elif "open documents" in command:
                    speak("Opening Documents")
                    open_documents()

                elif "open desktop" in command:
                    speak("Opening Desktop")
                    open_desktop()

                elif "shutdown" in command:
                    speak("Shutting down the PC")
                    shutdown_pc()

                elif "restart" in command:
                    speak("Restarting the PC")
                    restart_pc()

                elif "sleep" in command:
                    speak("Putting the PC to sleep")
                    sleep_pc()

                elif "lock" in command:
                    speak("Locking the PC")
                    lock_pc()

                elif "screenshot" in command:
                    speak("Taking a screenshot")
                    screenshot()

                elif "volume up" in command:
                    speak("Increasing volume")
                    volume_up()

                elif "volume down" in command:
                    speak("Decreasing volume")
                    volume_down()

                elif "mute" in command:
                    speak("Muting volume")
                    mute()

                elif "turn on wifi" in command:
                    speak("Turning on Wi-Fi")
                    wifi_on()

                elif "turn off wifi" in command:
                    speak("Turning off Wi-Fi")
                    wifi_off()

                elif "empty recycle bin" in command:
                    speak("Emptying the Recycle Bin")
                    empty_recycle_bin()

                elif (
                    "what is the time" in command
                    or "current time" in command
                ):
                    current_time_str = current_time()
                    speak(
                        f"The current time is {current_time_str}"
                    )

                elif (
                    "today's date" in command
                    or "current date" in command
                ):
                    current_date_str = current_date()
                    speak(
                        f"Today's date is {current_date_str}"
                    )

                elif "play music" in command:
                    speak("Playing music")
                    play_music()

                elif "open camera" in command:
                    speak("Opening Camera")
                    open_camera()

                elif (
                    "open dashboard" in command
                    or "show dashboard" in command
                    or "launch dashboard" in command
                ):
                    speak("Opening ZYRA Dashboard")
                    open_dashboard_in_edge(DASHBOARD_URL)

                elif "my favorite language is" in command:
                    language = command.replace(
                        "my favorite language is",
                        "",
                    ).strip()

                    remember(
                        "favorite_language",
                        language,
                    )

                    speak(
                        f"I'll remember that. Your favorite language is {language}."
                    )

                elif "what is my favorite language" in command:
                    language = recall("favorite_language")

                    if language:
                        speak(
                            f"Your favorite language is {language}."
                        )
                    else:
                        speak(
                            "I don't know your favorite language yet."
                        )

                elif is_system_monitor_intent(command):
                    # Start / show System Monitor, print ASCII card, broadcast to dashboard, and speak summary
                    metrics = get_system_metrics()

                    report = format_system_monitor_text(metrics)

                    print(f"\n{report}\n")

                    try:
                        broadcast_system_monitor_trigger(metrics)
                    except Exception:
                        pass

                    voice_text = get_voice_summary(metrics)

                    speak(voice_text)

                elif is_dns_intent(command):
                    # ZYRA DNS Lookup — real backend DNS queries streamed live
                    # to the dashboard panel with the spoken result delivered
                    # when the lookup completes.
                    handle_dns_analysis_voice(command)

                elif is_url_analysis_intent(command):
                    # ZYRA URL Analyzer — real backend scan streamed live to the
                    # dashboard panel (opens the URL Analyzer on the right) with
                    # the spoken result delivered when the analysis completes.
                    handle_url_analysis_voice(command)

                elif is_link_analysis_intent(command):
                    # Use the new real-time screen capture link analysis
                    # Captures screen OCR + clipboard, runs 8-check heuristic,
                    # and speaks the exact verdict directly to user
                    result = handle_analyze_link_intent(command)

                    # Print detailed report to console
                    if result.get("success") and result.get("checks"):
                        print(
                            f"\n🔗 URL: {result['url']}"
                        )

                        print(
                            f"📈 Risk Score: {result['score']}"
                        )

                        print(
                            f"⚖️  Verdict: {result['verdict']}"
                        )

                        print(
                            f"🗣️  Speech: {result['speech_text']}"
                        )

                elif is_nmap_intent(command):
                    # Network scanning with Nmap
                    # Discovers hosts, scans ports, detects services,
                    # and identifies security vulnerabilities
                    result = handle_nmap_intent(command)

                elif (
                    "exit" in command
                    or "quit" in command
                    or "goodbye" in command
                    or "shut it down" in command
                ):
                    speak(
                        "Goodbye. Have a nice day."
                    )

                    break

                else:
                    # Conversational answer: streaming STT → Ollama → TTS.
                    # The worker streams sentences into the TTS queue, so ZYRA
                    # starts speaking as soon as the first sentence exists and
                    # keeps talking while the model finishes the rest. The main
                    # loop immediately resumes listening (barge-in).
                    threading.Thread(
                        target=answer_voice_stream,
                        args=(spoken_text, turn),
                        name="zyra-voice-answer",
                        daemon=True,
                    ).start()

            except KeyboardInterrupt:
                stop_speaking(clear_queue=True)

                speak(
                    "Shutting down. Goodbye."
                )

                break

            except Exception as e:
                print("Error:", e)

                speak(
                    "Sorry, something went wrong."
                )

    finally:
        # Always run cleanup when the main loop exits
        cleanup()
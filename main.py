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

from listen import listen
from speak import speak
from brain import ask_ai
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
from backend.server import start_server_thread
from link_analysis import analyze_link, initialize_ml_model

# ========== Configuration ==========
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
DASHBOARD_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

# Global state for clean shutdown
server_thread = None
edge_process = None
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


def open_dashboard_in_edge(url):
    """
    Open the ZYRA dashboard in Microsoft Edge.
    Uses subprocess for direct control, with webbrowser fallback.

    Args:
        url: The dashboard URL to open (e.g. http://127.0.0.1:8080)
    """
    global edge_process

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
            print("   ✅ Dashboard opened in Microsoft Edge (fullscreen/kiosk mode)")
            return True
        except Exception as e:
            print(f"   ⚠️  Edge subprocess failed ({e}), trying webbrowser fallback...")

    # Fallback: use webbrowser module with Edge registration
    try:
        webbrowser.get("edge").open(url, new=2)
    except Exception:
        webbrowser.open(url, new=2)
    print("   ✅ Dashboard opened in browser")
    return True


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
            response = urllib.request.urlopen(health_url, timeout=2)
            if response.status == 200:
                print(f"   ✅ Backend server is ready (attempt {attempt})")
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
            print(f"   ⏳ Waiting... (attempt {attempt}/{max_retries})")
            time.sleep(retry_interval)

    print(f"   ⚠️  Server not ready after {max_retries} attempts — proceeding anyway")
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
    - Terminate the Edge browser process if we launched it
    - The backend server thread is a daemon and will exit automatically
    """
    global edge_process

    print("\n🧹 Cleaning up...")

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

    # Initialize ML model for link analysis (non-blocking, falls back to heuristics)
    print("\n📦 Initializing ML model for link analysis...")
    initialize_ml_model()

    # Start the backend server in background thread (non-blocking)
    server_thread = start_backend_server()

    # Wait for the server to be fully initialized and listening
    # This polls the /api/health endpoint with retries
    server_ready = wait_for_server(DASHBOARD_URL, max_retries=8, retry_interval=1.0)

    if server_ready:
        # Open the dashboard in Microsoft Edge
        open_dashboard_in_edge(DASHBOARD_URL)
    else:
        print("\n⚠️  Server may not be fully ready. Attempting to open dashboard anyway...")
        open_dashboard_in_edge(DASHBOARD_URL)

    print("\n✨ ZYRA is now running!")
    print("   🎤 Voice commands: Speak into your microphone")
    print("   🌐 Dashboard: Open in browser at", DASHBOARD_URL)
    print("   ⌨️  Say 'exit' or press Ctrl+C to quit\n")

    speak("Hello, I am Zyra. How can I help you today?")

    try:
        while running:
            try:
                command = listen()

                if not command:
                    continue

                command = command.lower()

                print(f"You : {command}")

                if command.startswith("close "):
                    app = command.replace("close ", "").strip()
                    response = close_app(app)
                    print(response)
                    speak(response)

                elif "open chrome" in command:
                    speak("Opening Chrome")
                    open_chrome()

                elif "open vscode" in command or "open visual studio code" in command:
                    speak("Opening Visual Studio Code")
                    open_vscode()

                elif "open notepad" in command:
                    speak("Opening Notepad")
                    open_notepad()

                elif "open calculator" in command:
                    speak("Opening Calculator")
                    open_calculator()

                elif "open cmd" in command or "open command prompt" in command:
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

                elif "open file explorer" in command or "open explorer" in command:
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
                    query = command.replace("search google for", "").strip()
                    speak(f"Searching Google for {query}")
                    search_google(query)

                elif "search youtube for" in command:
                    query = command.replace("search youtube for", "").strip()
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

                elif "what is the time" in command or "current time" in command:
                    current_time_str = current_time()
                    speak(f"The current time is {current_time_str}")

                elif "today's date" in command or "current date" in command:
                    current_date_str = current_date()
                    speak(f"Today's date is {current_date_str}")

                elif "play music" in command:
                    speak("Playing music")
                    play_music()

                elif "open camera" in command:
                    speak("Opening Camera")
                    open_camera()

                elif "open dashboard" in command or "show dashboard" in command or "launch dashboard" in command:
                    speak("Opening ZYRA Dashboard")
                    open_dashboard_in_edge(DASHBOARD_URL)

                elif "my favorite language is" in command:
                    language = command.replace("my favorite language is", "").strip()
                    remember("favorite_language", language)
                    speak(f"I'll remember that. Your favorite language is {language}.")

                elif "what is my favorite language" in command:
                    language = recall("favorite_language")
                    if language:
                        speak(f"Your favorite language is {language}.")
                    else:
                        speak("I don't know your favorite language yet.")

                elif "analyse this link" in command or "analyze this link" in command or "check this link" in command:
                    analyze_link()

                elif "exit" in command or "quit" in command or "goodbye" in command or "shut it down" in command:
                    speak("Goodbye. Have a nice day.")
                    break

                else:
                    answer = ask_ai(command)
                    print(f"Zyra : {answer}")
                    speak(answer)

            except KeyboardInterrupt:
                speak("Shutting down. Goodbye.")
                break

            except Exception as e:
                print("Error:", e)
                speak("Sorry, something went wrong.")

    finally:
        # Always run cleanup when the main loop exits
        cleanup()
import threading
import time
import os
import sys

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
from fullscreen_dashboard import open_dashboard_fullscreen

# ========== Configuration ==========
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
DASHBOARD_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


def start_backend_server():
    """Start the FastAPI backend server in a background thread"""
    print("\n" + "="*50)
    print("🚀 Starting ZYRA Backend Server...")
    print("="*50)
    
    # Start server WITHOUT opening browser - we'll handle fullscreen separately
    server_thread = start_server_thread(
        host=SERVER_HOST,
        port=SERVER_PORT,
        open_browser=False  # Don't open browser here, we'll use fullscreen
    )
    
    # Give the server a moment to start
    time.sleep(2)
    
    print(f"\n✅ Dashboard available at: {DASHBOARD_URL}")
    print("📡 WebSocket: ws://127.0.0.1:8080/ws")
    print("📋 API Docs: http://127.0.0.1:8080/docs")
    print("="*50 + "\n")
    
    return server_thread


def open_dashboard():
    """Open the ZYRA dashboard in FULLSCREEN kiosk mode using Microsoft Edge"""
    print(f"\n🌐 Opening ZYRA Dashboard in Fullscreen Mode...")
    open_dashboard_fullscreen(DASHBOARD_URL)


# ========== Main Entry Point ==========

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════╗
    ║          ZYRA AI ASSISTANT           ║
    ║     Voice + Dashboard + API          ║
    ╚══════════════════════════════════════╝
    """)
    
    # Start the backend server in background
    server_thread = start_backend_server()
    
    # Small delay to ensure server is up
    time.sleep(1)
    
    # Open the dashboard in FULLSCREEN mode
    open_dashboard()
    
    print("Zyra is now running...\n")
    
    speak("Hello, I am Zyra. How can I help you today?")
    
    while True:
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
                open_dashboard()
    
            
            elif "my favorite language is" in command:
                language = command.replace(
                "my favorite language is", ""
                ).strip()
    
                remember("favorite_language", language)
                speak(f"I'll remember that. Your favorite language is {language}.")
    
            elif "what is my favorite language" in command:
                language = recall("favorite_language")
    
                if language:
                    speak(f"Your favorite language is {language}.")
                else:
                    speak("I don't know your favorite language yet.")
    
    
    
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

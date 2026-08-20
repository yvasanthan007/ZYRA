"""
commands/open_app.py — System Control Commands (Cross-Platform)

Originally Windows-only, now supports Windows, macOS, and Linux.
"""

import os
import sys
import platform
import subprocess
import ctypes

# ── Platform Detection ──────────────────────────────────────
IS_WINDOWS = platform.system() == 'Windows'
IS_MAC = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

HOME = os.path.expanduser("~")


# ── URL / Web Browser Helpers ──────────────────────────────

def _open_url(url):
    """Open a URL in the default browser (cross-platform)."""
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        if IS_MAC:
            subprocess.run(['open', url])
        elif IS_LINUX:
            subprocess.run(['xdg-open', url])
        else:  # Windows
            os.startfile(url)


# ── Application Launchers ──────────────────────────────────

def open_chrome():
    chrome_paths = {
        'Windows': r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        'Darwin': '/Applications/Google Chrome.app',
        'Linux': '/usr/bin/google-chrome',
    }
    plat = platform.system()
    p = chrome_paths.get(plat, '')
    if os.path.exists(p):
        if IS_WINDOWS:
            os.startfile(p)
        else:
            subprocess.run([p, 'https://www.google.com'])
    else:
        _open_url("https://www.google.com")


def open_vscode():
    vscode_paths = {
        'Windows': os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Microsoft VS Code', 'Code.exe'),
        'Darwin': '/Applications/Visual Studio Code.app/Contents/MacOS/Electron',
        'Linux': os.path.expanduser('~/.local/bin/code'),
    }
    plat = platform.system()
    p = vscode_paths.get(plat, '')
    if os.path.exists(p):
        if IS_WINDOWS:
            os.startfile(p)
        else:
            subprocess.Popen([p])
    else:
        subprocess.run(['code'], capture_output=True)


def open_notepad():
    if IS_WINDOWS:
        os.system("notepad")
    elif IS_MAC:
        subprocess.run(['open', '-a', 'TextEdit'])
    else:
        subprocess.run(['gedit']) or subprocess.run(['nano'])


def open_calculator():
    if IS_WINDOWS:
        os.system("calc")
    elif IS_MAC:
        subprocess.run(['open', '-a', 'Calculator'])
    else:
        subprocess.run(['gnome-calculator']) or subprocess.run(['kcalc'])


def open_cmd():
    if IS_WINDOWS:
        os.system("start cmd")
    elif IS_MAC:
        subprocess.run(['open', '-a', 'Terminal'])
    else:
        subprocess.run(['x-terminal-emulator']) or subprocess.run(['gnome-terminal'])


def open_powershell():
    if IS_WINDOWS:
        os.system("start powershell")
    elif IS_MAC or IS_LINUX:
        open_cmd()


def open_task_manager():
    if IS_WINDOWS:
        os.system("taskmgr")
    elif IS_MAC:
        subprocess.run(['open', '-a', 'Activity Monitor'])
    else:
        subprocess.run(['gnome-system-monitor']) or subprocess.run(['htop'])


def open_control_panel():
    if IS_WINDOWS:
        os.system("control")
    elif IS_MAC:
        subprocess.run(['open', 'x-apple.systempreferences:'])
    else:
        subprocess.run(['gnome-control-center']) or _open_url("settings://")


def open_file_explorer():


#------------------Web Browser---------------------#


def open_google():
    webbrowser.open("https://www.google.com")

def open_youtube():
    webbrowser.open("https://www.youtube.com")

def open_github():
    webbrowser.open("https://github.com")

def open_chatgpt():
    webbrowser.open("https://chatgpt.com")

def open_gmail():
    webbrowser.open("https://mail.google.com")

def open_leetcode():
    webbrowser.open("https://leetcode.com")

def open_linkedin():
    webbrowser.open("https://linkedin.com")


def search_google(query):
    webbrowser.open(
        f"https://www.google.com/search?q={query}"
    )

def search_youtube(query):
    webbrowser.open(
        f"https://www.youtube.com/results?search_query={query}"
    )



#------------------file explorer--------------------#

def open_downloads():
    os.startfile(os.path.join(HOME, "Downloads"))

def open_documents():
    os.startfile(os.path.join(HOME, "Documents"))

def open_desktop():
    os.startfile(os.path.join(HOME, "Desktop"))


#--------------------PC : shutdown,restart,sleep ---------------#


def shutdown_pc():
    os.system("shutdown /s /t 1")

def restart_pc():
    os.system("shutdown /r /t 1")

def sleep_pc():
    os.system("rundll32.exe powrprof.dll,SetSuspendState Sleep")


#------------------Lock PC-----------------------#

def lock_pc():
    ctypes.windll.user32.LockWorkStation()



#----------------Screenshot--------------------#

def screenshot():
    img = pyautogui.screenshot()
    img.save("screenshot.png")

#----------------volume : up,down,mute---------------------#

def volume_up():
    pyautogui.press("volumeup")

def volume_down():
    pyautogui.press("volumedown")

def mute():
    pyautogui.press("volumemute")



#----------------Wifi------------------------------#

def wifi_on():
    os.system('netsh interface set interface "Wi-Fi" enable')

def wifi_off():
    os.system('netsh interface set interface "Wi-Fi" disable')




#--------------Recycle bin------------------------#

def empty_recycle_bin():
    winshell.recycle_bin().empty(confirm=False)



#-------------Current Date & Time---------------#

def current_time():
    return datetime.now().strftime("%I:%M %p")

def current_date():
    return datetime.now().strftime("%d %B %Y")


#--------------play music----------------------#

def play_music():
    os.startfile(os.path.join(HOME, "Music"))

#--------------Open Camera---------------------#

def open_camera():
    os.system("start microsoft.windows.camera:")

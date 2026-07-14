import psutil

#------------------Applications to Close---------------------#


APPS = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",

    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",

    "notepad": "notepad.exe",

    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",

    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",

    "powershell": "powershell.exe",

    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",

    "task manager": "Taskmgr.exe",

    "spotify": "Spotify.exe",

    "discord": "Discord.exe",

    "telegram": "Telegram.exe",

    "whatsapp": "WhatsApp.exe",

    "edge": "msedge.exe",

    "paint": "mspaint.exe",
}


def close_app(app_name):
    """
    Closes an application by its friendly name.
    Returns a message for Zyra to speak.
    """

    app_name = app_name.lower().strip()

    if app_name not in APPS:
        return f"I don't know how to close {app_name}."

    process_name = APPS[app_name]

    closed = False

    for process in psutil.process_iter(['pid', 'name']):
        try:
            if process.info['name'] and process.info['name'].lower() == process_name.lower():
                process.terminate()
                process.wait(timeout=3)
                closed = True
        except (psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.TimeoutExpired):
            pass

    if closed:
        return f"{app_name} closed successfully."

    return f"{app_name} is not running."


if __name__ == "__main__":
    app = input("Enter app name: ")
    print(close_app(app))
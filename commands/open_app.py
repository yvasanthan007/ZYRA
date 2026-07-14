import os
import ctypes
import pyautogui
import winshell
import webbrowser
from datetime import datetime


#------------------Open Applications---------------------#

def open_chrome():
    os.startfile(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

def open_vscode():
    os.startfile(r"C:\Users\Vasanthan Y\AppData\Local\Programs\Microsoft VS Code\Code.exe")

def open_notepad():
    os.system("notepad")

def open_calculator():
    os.system("calc")

def open_cmd():
    os.system("start cmd")

def open_powershell():
    os.system("start powershell")

def open_task_manager():
    os.system("taskmgr")

def open_control_panel():
    os.system("control")

def open_file_explorer():
    os.system("explorer")

def open_settings():
    os.system("start ms-settings:")


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
    os.startfile(r"C:\Users\Vasanthan Y\Downloads")

def open_documents():
    os.startfile(r"C:\Users\Vasanthan Y\Documents")

def open_desktop():
    os.startfile(r"C:\Users\Vasanthan Y\Desktop")


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
    os.startfile(r"C:\Users\Vasanthan Y\Music")

#--------------Open Camera---------------------#

def open_camera():
    os.system("start microsoft.windows.camera:")
from listen import listen
from speak import speak
from brain import ask_ai
from commands.open_app import *
from commands.close_app import close_app
from memory import remember, recall



print("Zyra is now running...\n")

speak("Hello, I am Zyra. How can I help you today?")

while True:
    try:
        command = listen()

        if not command:
            continue

        command = command.lower().strip()

        print(f"You : {command}")

        if command.startswith("close "):
            app = command.replace("close ", "").strip()

            response = close_app(app)

            print(response)
            speak(response)

        if "open chrome" in command:
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

        elif "what is the Today's date" in command or "current date" in command:
            current_date_str = current_date()
            speak(f"Today's date is {current_date_str}")

        elif "play music" in command:
            speak("Playing music")
            play_music()
        
        elif "open camera" in command:
            speak("Opening Camera")
            open_camera()

        
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



        elif "exit" in command or "quit" in command or "goodbye" in command or "Shut it down" in command:
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
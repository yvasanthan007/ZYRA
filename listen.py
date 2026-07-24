import speech_recognition as sr

recognizer = sr.Recognizer()

# Improve recognition in noisy environments
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8


def listen():
    with sr.Microphone() as source:
        print("\n🎤 Listening...")

        recognizer.adjust_for_ambient_noise(source, duration=0.5)

        try:
            audio = recognizer.listen(
                source,
                timeout=5,
                phrase_time_limit=10
            )

        except sr.WaitTimeoutError:
            return ""

    try:
        command = recognizer.recognize_google(audio)

        return command

    except sr.UnknownValueError:
        print("❌ I couldn't understand that.")
        return ""

    except sr.RequestError:
        print("❌ Unable to connect to Google's speech service.")
        return ""

    except Exception as e:
        print("Error:", e)
        return "" 
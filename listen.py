# Try to import speech recognition, use fallback if not available
try:
    import speech_recognition as sr
    SR_AVAILABLE = True
    recognizer = sr.Recognizer()
    # Improve recognition in noisy environments
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8
except ImportError:
    SR_AVAILABLE = False
    print("⚠️  Speech recognition not available - using text input fallback")


def listen():
    """
    Listen for voice command or fallback to text input.
    
    Returns:
        str: The recognized command or text input
    """
    if not SR_AVAILABLE:
        # Fallback to text input when speech recognition is not available
        try:
            command = input("\n⌨️  Type your command: ").strip()
            return command
        except (EOFError, KeyboardInterrupt):
            return ""
    
    try:
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
                print("⏱️  No speech detected. Type your command:")
                return input("> ").strip()

        try:
            command = recognizer.recognize_google(audio)
            return command

        except sr.UnknownValueError:
            print("❌ I couldn't understand that. Type your command:")
            return input("> ").strip()

        except sr.RequestError:
            print("❌ Unable to connect to Google's speech service. Type your command:")
            return input("> ").strip()

        except Exception as e:
            print(f"Error: {e}. Type your command:")
            return input("> ").strip()

    except Exception as e:
        print(f"Microphone error: {e}. Type your command:")
        return input("> ").strip()

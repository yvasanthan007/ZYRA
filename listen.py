import speech_recognition as sr

recognizer = sr.Recognizer()

# Improve recognition in noisy environments
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8


def listen():
    """Listen for voice input from the microphone with automatic silence detection."""
    print("\n🎤 Listening...")

    # Primary method: speech_recognition Microphone (auto-stops when user stops speaking)
    try:
        with sr.Microphone() as source:
            # Quick ambient noise adjustment
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            audio = recognizer.listen(source, timeout=6, phrase_time_limit=10)
            command = recognizer.recognize_google(audio)
            return command
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except sr.RequestError:
        print("❌ Unable to connect to Google's speech service.")
        return ""
    except Exception:
        # Fallback to sounddevice if sr.Microphone is unavailable on some hardware
        try:
            import sounddevice as sd
            import numpy as np

            sample_rate = 16000
            channels = 1
            duration = 5  # Reduced fallback duration

            audio_data = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=channels,
                dtype=np.int16,
                blocking=True
            )
            audio_bytes = audio_data.tobytes()
            audio = sr.AudioData(audio_bytes, sample_rate=sample_rate, sample_width=2)
            command = recognizer.recognize_google(audio)
            return command
        except (sr.UnknownValueError, sr.WaitTimeoutError):
            return ""
        except sr.RequestError:
            print("❌ Unable to connect to Google's speech service.")
            return ""
        except Exception as e:
            print(f"❌ Microphone error: {e}")
            return ""


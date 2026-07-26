import speech_recognition as sr
import sounddevice as sd
import numpy as np

recognizer = sr.Recognizer()

# Improve recognition in noisy environments
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8


def listen():
    """Listen for voice input from the microphone using sounddevice."""
    try:
        print("\n🎤 Listening...")

        # Audio parameters
        sample_rate = 16000  # 16kHz sampling rate
        channels = 1  # Mono audio
        duration = 10  # Maximum recording duration in seconds
        chunk_size = 1024

        # Record audio using sounddevice
        try:
            audio_data = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=channels,
                dtype=np.int16,
                blocking=True
            )
            
            # Convert numpy array to bytes
            audio_bytes = audio_data.tobytes()
            
            # Create AudioData object for speech_recognition
            audio = sr.AudioData(
                audio_bytes,
                sample_rate=sample_rate,
                sample_width=2  # 16-bit = 2 bytes
            )

        except Exception as e:
            print(f"❌ Recording error: {e}")
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

    except OSError as e:
        print(f"❌ Microphone error: {e}")
        return ""
    except Exception as e:
        print(f"❌ Listening error: {e}")
        return ""

import asyncio
import os
import tempfile

import edge_tts
import pygame

VOICE = "en-US-AriaNeural"   # Natural Female Voice

pygame.mixer.init()


async def _speak_async(text):
    # Use a temporary file to avoid conflicts
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, "zyra_voice.mp3")

    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_file)

    pygame.mixer.music.load(output_file)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        await asyncio.sleep(0.1)

    pygame.mixer.music.unload()

    # Clean up temp file
    try:
        if os.path.exists(output_file):
            os.remove(output_file)
    except Exception:
        pass


def speak(text):
    if not text:
        return

    print(f"Zyra: {text}")

    try:
        # Check if mixer is initialized
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        
        asyncio.run(_speak_async(text))
    except RuntimeError:
        # If event loop is already running, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_speak_async(text))
        finally:
            loop.close()
    except Exception as e:
        print(f"TTS Error: {e}")
        # Continue without TTS - voice is optional

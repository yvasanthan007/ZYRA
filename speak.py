import asyncio
import os

import edge_tts
import pygame

VOICE = "en-US-AriaNeural"   # Natural Female Voice

pygame.mixer.init()


async def _speak_async(text):
    output_file = "zyra_voice.mp3"

    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_file)

    pygame.mixer.music.load(output_file)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        await asyncio.sleep(0.1)

    pygame.mixer.music.unload()

    if os.path.exists(output_file):
        os.remove(output_file)


def speak(text):
    if not text:
        return

    print(f"Zyra: {text}")

    try:
        asyncio.run(_speak_async(text))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_speak_async(text))
        loop.close()
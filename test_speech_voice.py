"""Regression tests for the configured Jenny Edge TTS voice and fallback."""
import asyncio
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import speak


class SpeechVoiceTests(unittest.TestCase):
    def test_every_language_uses_configured_jenny_voice(self):
        for text in ("Hello", "नमस्ते", "வணக்கம்"):
            self.assertEqual(speak._get_voice_for_text(text), "en-US-JennyNeural")

    def test_configured_voice_is_jenny_with_ordered_fallbacks(self):
        self.assertEqual(speak.VOICE, "en-US-JennyNeural")
        self.assertEqual(speak.DEFAULT_VOICE, "en-US-JennyNeural")
        self.assertEqual(
            speak.FALLBACK_VOICES,
            ("en-US-AriaNeural", "en-US-AvaNeural", "en-US-EmmaNeural"),
        )

    def test_sapi_fallback_is_only_used_if_edge_synthesis_fails(self):
        with patch.object(speak, "_speak_async", return_value=False), \
             patch.object(speak, "_sapi_fallback", return_value=True) as fallback:
            speak.speak("Test audio")
        fallback.assert_called_once_with("Test audio")


class SingleInFlightSpeechTests(unittest.TestCase):
    """Regression: concurrent speak requests must never overlap on the mixer."""

    def tearDown(self):
        # Never leak a stop request or a held lock into the next test.
        speak._stop_requested.clear()
        self.assertFalse(speak._speak_lock.locked(),
                         "speak() leaked the single-in-flight lock")

    def test_concurrent_speak_calls_never_overlap(self):
        state = {"active": 0, "peak": 0, "done": 0}
        guard = threading.Lock()

        async def fake_render(text):
            with guard:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.05)
            with guard:
                state["active"] -= 1
                state["done"] += 1
            return True

        threads = [
            threading.Thread(target=speak.speak, args=(f"line {i}",))
            for i in range(4)
        ]
        with patch.object(speak, "_speak_async", fake_render), \
             patch.object(speak, "_sapi_fallback", return_value=False):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        self.assertEqual(state["done"], 4, "a speak() call never completed")
        self.assertEqual(state["peak"], 1,
                         "audio overlapped: peak concurrency was "
                         f"{state['peak']}")

    def test_sequential_speak_calls_preserve_order(self):
        played = []

        async def fake_render(text):
            played.append(text)
            return True

        with patch.object(speak, "_speak_async", fake_render), \
             patch.object(speak, "_sapi_fallback", return_value=False):
            speak.speak("first sentence")
            speak.speak("second sentence")

        self.assertEqual(played, ["first sentence", "second sentence"])

    def test_synthesis_failure_releases_lock_and_runs_sapi_fallback(self):
        async def always_fail(text):
            return False

        with patch.object(speak, "_speak_async", always_fail), \
             patch.object(speak, "_sapi_fallback", return_value=True) as fallback:
            speak.speak("edge down")
            # Lock must be free for the very next utterance.
            self.assertFalse(speak._speak_lock.locked())
            speak.speak("next utterance")

        self.assertEqual(fallback.call_count, 2)
        self.assertFalse(speak._speak_lock.locked())

    def test_unexpected_exception_releases_lock_without_crashing(self):
        async def boom(text):
            raise RuntimeError("synthesis exploded")

        with patch.object(speak, "_speak_async", boom), \
             patch.object(speak, "_sapi_fallback", return_value=False):
            speak.speak("will fail")   # must not raise out of speak()
            self.assertFalse(speak._speak_lock.locked())
            speak.speak("still works") # pipeline recovered

    def test_failed_synthesis_cleans_up_temp_file(self):
        output_file = os.path.join(tempfile.gettempdir(), "zyra_voice.mp3")

        async def fail_after_partial_write(text, path):
            with open(path, "wb") as fh:
                fh.write(b"partial audio bytes")
            return False

        with patch.object(speak, "_render_audio", fail_after_partial_write):
            ok = asyncio.run(speak._speak_async("hello"))

        self.assertFalse(ok)
        self.assertFalse(os.path.exists(output_file),
                         "failed synthesis leaked the temp audio file")

    def test_successful_playback_cleans_up_temp_file(self):
        output_file = os.path.join(tempfile.gettempdir(), "zyra_voice.mp3")

        async def write_audio(text, path):
            with open(path, "wb") as fh:
                fh.write(b"fake mp3")
            return True

        with patch.object(speak, "_render_audio", write_audio), \
             patch.object(speak.pygame.mixer.music, "load"), \
             patch.object(speak.pygame.mixer.music, "play"), \
             patch.object(speak.pygame.mixer.music, "unload"), \
             patch.object(speak.pygame.mixer.music, "get_busy", return_value=False):
            ok = asyncio.run(speak._speak_async("hello"))

        self.assertTrue(ok)
        self.assertFalse(os.path.exists(output_file),
                         "successful playback leaked the temp audio file")


class StopSpeakingTests(unittest.TestCase):
    """Regression: stop must halt real backend audio and free the lock."""

    def tearDown(self):
        speak._stop_requested.clear()

    def test_stop_flag_aborts_synthesis_before_any_edge_call(self):
        speak._stop_requested.set()
        with patch.object(speak.edge_tts, "Communicate") as communicate:
            ok = asyncio.run(speak._render_audio("hello", "unused.mp3"))
        self.assertFalse(ok)
        communicate.assert_not_called()

    def test_stop_interrupts_playback_and_skips_sapi_fallback(self):
        playback = {"stopped": False}
        started = threading.Event()

        async def write_audio(text, path):
            with open(path, "wb") as fh:
                fh.write(b"fake mp3")
            return True

        def fake_get_busy():
            return not playback["stopped"]

        def fake_stop():
            playback["stopped"] = True

        fallback_calls = []
        errors = []

        def run_speak():
            try:
                speak.speak("interrupt me")
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        with patch.object(speak, "_render_audio", write_audio), \
             patch.object(speak, "_sapi_fallback",
                          side_effect=lambda t: fallback_calls.append(t)), \
             patch.object(speak.pygame.mixer.music, "load"), \
             patch.object(speak.pygame.mixer.music, "play",
                          side_effect=started.set), \
             patch.object(speak.pygame.mixer.music, "unload"), \
             patch.object(speak.pygame.mixer.music, "get_busy", fake_get_busy), \
             patch.object(speak.pygame.mixer.music, "stop", fake_stop):
            worker = threading.Thread(target=run_speak, daemon=True)
            worker.start()
            self.assertTrue(started.wait(5), "playback never started")
            self.assertTrue(speak.stop_speaking(),
                            "stop_speaking() did not report halted playback")
            worker.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertFalse(worker.is_alive(), "speak() ignored the stop request")
        self.assertTrue(playback["stopped"],
                        "backend pygame playback was not actually stopped")
        self.assertEqual(fallback_calls, [],
                         "SAPI fallback started new audio after a stop")
        self.assertFalse(speak._speak_lock.locked(),
                         "stop left the single-in-flight lock held")

    def test_next_utterance_plays_normally_after_a_stop(self):
        played = []

        async def fake_render(text):
            played.append(text)
            return True

        with patch.object(speak, "_speak_async", fake_render), \
             patch.object(speak, "_sapi_fallback", return_value=False):
            speak.speak("after stop")

        self.assertEqual(played, ["after stop"])


class SpeakEndpointTests(unittest.TestCase):
    """Regression: /api/speak stays non-blocking and /api/speak/stop works."""

    @classmethod
    def setUpClass(cls):
        from backend import server
        cls.server = server

    def test_empty_text_is_rejected(self):
        response = asyncio.run(self.server.speak_endpoint({"text": ""}))
        self.assertEqual(response.status_code, 400)

    def test_speak_endpoint_delegates_to_serialized_pipeline(self):
        with patch.object(self.server, "speak_text") as speak_text:
            result = asyncio.run(
                self.server.speak_endpoint({"text": "hello zyra"}))
        speak_text.assert_called_once_with("hello zyra")
        self.assertEqual(result, {"success": True, "data": "Speaking"})

    def test_speak_endpoint_returns_500_when_pipeline_rejects(self):
        with patch.object(self.server, "speak_text",
                          side_effect=RuntimeError("boom")):
            response = asyncio.run(
                self.server.speak_endpoint({"text": "hello"}))
        self.assertEqual(response.status_code, 500)

    def test_stop_endpoint_stops_backend_playback(self):
        with patch.object(self.server, "stop_speaking",
                          return_value=True) as stop:
            result = asyncio.run(self.server.speak_stop_endpoint())
        stop.assert_called_once_with()
        self.assertEqual(result["success"], True)
        self.assertEqual(result["data"], "Stopped")
        self.assertTrue(result["stopped_playback"])

    def test_stop_endpoint_reports_idle_pipeline(self):
        with patch.object(self.server, "stop_speaking", return_value=False):
            result = asyncio.run(self.server.speak_stop_endpoint())
        self.assertTrue(result["success"])
        self.assertFalse(result["stopped_playback"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
test_voice_pipeline.py — ZYRA voice pipeline regression tests.

Covers the guarantees the voice pipeline must keep:

  1. Exactly ONE listening session can be active (duplicate microphone
     processing is refused, never queued).
  2. One utterance ⇒ one transcript ⇒ one AI request ⇒ one TTS queue entry
     (nothing is transcribed, requested or synthesized twice).
  3. Sentence-level streaming: the first sentence is handed to TTS while the
     model is still generating the rest.
  4. Interrupt (barge-in): stop_speaking() stops playback, clears the queue and
     invalidates in-flight synthesis so an interrupted answer cannot return.
  5. Internal logs / error text are never spoken.

Everything here runs offline (no microphone, no audio device, no Ollama).
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brain
import listen
import speak


class ListeningSessionTests(unittest.TestCase):
    def test_only_one_listening_session_at_a_time(self):
        # Hold the module's capture lock: a second (duplicate) listen() must
        # refuse immediately instead of opening a second microphone stream.
        self.assertTrue(listen._listen_lock.acquire(blocking=False))
        try:
            started = time.monotonic()
            result = listen.listen(timeout=5.0)
            elapsed = time.monotonic() - started
        finally:
            listen._listen_lock.release()
        self.assertEqual(result, "")
        self.assertLess(elapsed, 0.5)

    def test_stop_listening_flag_is_reset_per_session(self):
        listen.stop_listening()
        self.assertTrue(listen._stop_requested.is_set())
        listen.clear_stop()
        self.assertFalse(listen._stop_requested.is_set())

    def test_hallucination_filter_drops_noise_transcripts(self):
        for text in ("Thank you.", "you", "...", "yeah", "Thank you for watching."):
            self.assertTrue(listen._looks_like_hallucination(text, 1.0), text)
        self.assertTrue(listen._looks_like_hallucination("you you you you", 2.0))
        self.assertFalse(
            listen._looks_like_hallucination("what is ethical hacking", 2.0)
        )

    def test_echo_guard_rejects_zyra_own_voice(self):
        with mock.patch.object(speak, "recent_spoken",
                               return_value=["Ethical hacking is authorized "
                                             "security testing."]):
            self.assertTrue(
                listen._is_echo("ethical hacking is authorized security testing")
            )
            self.assertFalse(listen._is_echo("open chrome now please"))


class TtsQueueTests(unittest.TestCase):
    def tearDown(self):
        speak.stop_speaking(clear_queue=True)

    def test_internal_logs_and_errors_are_never_spoken(self):
        for text in ("brain: AI error after 10.0s: timed out",
                     "⚠️  TTS render error: boom",
                     "print('debug')",
                     "   ",
                     "🎤"):
            self.assertEqual(speak.sanitize_tts_text(text), "")
            self.assertFalse(speak.speak_async(text))

    def test_markdown_and_emoji_are_cleaned_not_read_aloud(self):
        cleaned = speak.sanitize_tts_text(
            "**Ethical hacking** is `authorized` testing 🎤 — [see docs](http://x.y)"
        )
        self.assertEqual(cleaned, "Ethical hacking is authorized testing — see docs")

    def test_sentence_is_queued_exactly_once(self):
        rendered = []

        def fake_render(text, output_file):
            rendered.append(text)
            with open(output_file, "wb") as handle:
                handle.write(b"fake")
            return True

        with mock.patch.object(speak, "_render_with_voice_fallback", fake_render), \
                mock.patch.object(speak, "_ensure_mixer", return_value=False):
            speak.speak("Ethical hacking is authorized testing.")
            speak.wait_until_done(timeout=10)
        self.assertEqual(rendered, ["Ethical hacking is authorized testing."])

    def test_interrupt_clears_the_queue_and_invalidates_synthesis(self):
        started = threading.Event()
        release = threading.Event()

        def slow_render(text, output_file):
            started.set()
            release.wait(5)
            with open(output_file, "wb") as handle:
                handle.write(b"fake")
            return True

        with mock.patch.object(speak, "_render_with_voice_fallback", slow_render), \
                mock.patch.object(speak, "_ensure_mixer", return_value=False):
            for sentence in ("First sentence.", "Second sentence.", "Third sentence."):
                speak.speak_async(sentence)
            self.assertTrue(started.wait(5))
            speak.stop_speaking()                 # barge-in
            release.set()
            time.sleep(0.4)
            self.assertFalse(speak.is_speaking())  # queue + playback dropped
            with speak._cond:
                self.assertEqual(speak._outstanding, 0)


class VoiceTurnPipelineTests(unittest.TestCase):
    """One utterance ⇒ one AI request ⇒ one TTS queue entry, in order."""

    def setUp(self):
        brain.clear_conversation()
        speak.stop_speaking(clear_queue=True)

    def tearDown(self):
        speak.stop_speaking(clear_queue=True)

    def test_single_utterance_produces_a_single_streamed_request(self):
        import main  # imported here so the offline tests above stay light

        spoken = []

        def fake_stream(question, session_id=None):
            self.assertEqual(question, "What is ethical hacking?")
            yield "Ethical hacking is authorized security testing."
            yield "It is done with permission."

        turn = main.start_voice_turn()
        with mock.patch.object(main, "ask_ai_stream", fake_stream), \
                mock.patch.object(main, "speak_async",
                                  side_effect=lambda text: spoken.append(text) or True):
            main.answer_voice_stream("What is ethical hacking?", turn)

        self.assertEqual(
            spoken,
            ["Ethical hacking is authorized security testing.",
             "It is done with permission."],
        )

    def test_a_newer_turn_cancels_the_previous_answer(self):
        import main

        spoken = []

        def slow_stream(question, session_id=None):
            yield "First sentence."
            main.start_voice_turn()          # user interrupts with a new request
            time.sleep(0.05)
            yield "Stale sentence that must never be spoken."

        turn = main.start_voice_turn()
        with mock.patch.object(main, "ask_ai_stream", slow_stream), \
                mock.patch.object(main, "speak_async",
                                  side_effect=lambda text: spoken.append(text) or True):
            main.answer_voice_stream("first question", turn)

        self.assertIn("First sentence.", spoken)
        self.assertNotIn("Stale sentence that must never be spoken.", spoken)


if __name__ == "__main__":
    unittest.main()

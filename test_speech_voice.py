"""Regression tests for the configured Jenny Edge TTS voice and fallback."""
import unittest
from unittest.mock import patch

import speak


class SpeechVoiceTests(unittest.TestCase):
    def test_every_language_uses_configured_jenny_voice(self):
        for text in ("Hello", "नमस्ते", "வணக்கம்"):
            self.assertEqual(speak._get_voice_for_text(text), "en-US-JennyNeural")

    def test_configured_voice_is_jenny_edge_voice(self):
        self.assertEqual(speak.VOICE, "en-US-JennyNeural")
        self.assertEqual(speak.DEFAULT_VOICE, "en-US-JennyNeural")

    def test_sapi_fallback_is_only_used_if_edge_synthesis_fails(self):
        with patch.object(speak, "_speak_async", return_value=False), \
             patch.object(speak, "_sapi_fallback", return_value=True) as fallback:
            speak.speak("Test audio")
        fallback.assert_called_once_with("Test audio")

if __name__ == "__main__":
    unittest.main(verbosity=2)

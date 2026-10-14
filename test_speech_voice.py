"Regression tests for TTS voice consistency and audible fallback."""
import unittest
from unittest.mock import patch
import speak
class SpeechVoiceTests(unittest.TestCase):
    def test_voice_is_consistent_for_english_hindi_and_tamil_text(self):
        for text in ("Hello", "नमस्ते", "வணக்கம்"):
            self.assertEqual(speak._get_voice_for_text(text), speak.VOICE)

    def test_sapi_fallback_is_available_when_edge_fails(self):
        with patch.object(speak, "_speak_async", return_value=False), \
             patch.object(speak, "_sapi_fallback", return_value=True) as fallback:
            speak.speak("Test audio")
        fallback.assert_called_once_with("Test audio")

if __name__ == "__main__":
    unittest.main(verbosity=2)

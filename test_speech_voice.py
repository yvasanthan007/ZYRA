<<<<<<< HEAD
"""Regression tests for TTS voice consistency and audible fallback.

ZYRA's voice must stay female on every path:
  * Edge TTS (primary) — en-US-JennyNeural / hi-IN-SwaraNeural /
    ta-IN-PallaviNeural are all female voices.
  * Windows SAPI fallback (Edge offline) — must select an explicitly female
    installed voice instead of the system default (Microsoft David, male).
"""
import unittest
from unittest.mock import patch

import speak


class SpeechVoiceTests(unittest.TestCase):
    def test_voice_is_consistent_for_english_hindi_and_tamil_text(self):
        # Every voice ZYRA can pick must be a known female Edge voice, so the
        # assistant never switches to a male voice mid-conversation.
        female_voices = {
            "en-US-JennyNeural",
            "hi-IN-SwaraNeural",
            "ta-IN-PallaviNeural",
        }
        for text in ("Hello", "नमस्ते", "வணக்கம்"):
            self.assertIn(speak._get_voice_for_text(text), female_voices)

    def test_default_voice_is_previous_female_edge_voice(self):
        # Historical project default from the original voice implementation.
        self.assertEqual(speak.VOICE, "en-US-JennyNeural")

    def test_sapi_fallback_selects_a_female_voice(self):
        # The offline fallback must not rely on the system default token
        # (Microsoft David - Male); it has to request a female voice first.
        with patch.object(speak.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(speak._sapi_fallback("Test audio"))
        run.assert_called_once()
        command = " ".join(str(part) for part in run.call_args[0][0])
        self.assertIn("Zira", command)
        self.assertIn("Female", command)
=======
"Regression tests for TTS voice consistency and audible fallback."""
import unittest
from unittest.mock import patch
import speak
class SpeechVoiceTests(unittest.TestCase):
    def test_voice_is_consistent_for_english_hindi_and_tamil_text(self):
        for text in ("Hello", "नमस्ते", "வணக்கம்"):
            self.assertEqual(speak._get_voice_for_text(text), speak.VOICE)
>>>>>>> 715a3dab4f0f579906d88f9e1afabe99b832d8a8

    def test_sapi_fallback_is_available_when_edge_fails(self):
        with patch.object(speak, "_speak_async", return_value=False), \
             patch.object(speak, "_sapi_fallback", return_value=True) as fallback:
            speak.speak("Test audio")
        fallback.assert_called_once_with("Test audio")

<<<<<<< HEAD

=======
>>>>>>> 715a3dab4f0f579906d88f9e1afabe99b832d8a8
if __name__ == "__main__":
    unittest.main(verbosity=2)
